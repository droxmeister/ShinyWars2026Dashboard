"""Google Sheets I/O for the Shiny Wars dashboard."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Pixel widths applied after every generated-tab refresh.  Keeping this here
# makes the output deterministic even when an old template contained merges,
# fills or oversized columns.
GENERATED_SHEET_COLUMN_WIDTHS: dict[str, tuple[int, ...]] = {
    "Sync Status": (260, 240),
    "Team Checklist": (220, 90, 220, 80, 105, 430),
    "Player Summary": (220, 115, 115, 135, 330, 180, 125),
}


@dataclass(frozen=True)
class SheetInput:
    players: list[dict[str, str]]
    catches: list[dict[str, str]]


def _rows_to_dicts(values: list[list[Any]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    result: list[dict[str, str]] = []
    for raw_row in values[1:]:
        padded = list(raw_row) + [""] * max(0, len(headers) - len(raw_row))
        row = {headers[index]: str(padded[index]).strip() for index in range(len(headers))}
        if any(row.values()):
            result.append(row)
    return result


def _credentials_from_env():
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def create_service():
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=_credentials_from_env(), cache_discovery=False)


def read_sheet_input(spreadsheet_id: str) -> SheetInput:
    service = create_service()
    response = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=["Players!A1:D100", "Catches!A1:F5000"],
            majorDimension="ROWS",
        )
        .execute()
    )
    ranges = response.get("valueRanges", [])
    players_values = ranges[0].get("values", []) if len(ranges) > 0 else []
    catches_values = ranges[1].get("values", []) if len(ranges) > 1 else []
    return SheetInput(
        players=_rows_to_dicts(players_values),
        catches=_rows_to_dicts(catches_values),
    )


def _sheet_metadata(service, spreadsheet_id: str) -> dict[str, dict[str, int]]:
    metadata = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields=(
                "sheets(properties(sheetId,title,"
                "gridProperties(rowCount,columnCount)))"
            ),
        )
        .execute()
    )
    result: dict[str, dict[str, int]] = {}
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        title = str(properties.get("title", ""))
        grid = properties.get("gridProperties", {})
        result[title] = {
            "sheet_id": int(properties["sheetId"]),
            "row_count": int(grid.get("rowCount", 1000)),
            "column_count": int(grid.get("columnCount", 26)),
        }
    return result


def _ensure_sheets(
    service,
    spreadsheet_id: str,
    titles: Iterable[str],
) -> dict[str, dict[str, int]]:
    metadata = _sheet_metadata(service, spreadsheet_id)
    requests = [
        {"addSheet": {"properties": {"title": title}}}
        for title in titles
        if title not in metadata
    ]
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
        metadata = _sheet_metadata(service, spreadsheet_id)
    return metadata


def _hex_to_rgb(hex_color: str) -> dict[str, float]:
    value = hex_color.lstrip("#")
    return {
        "red": int(value[0:2], 16) / 255.0,
        "green": int(value[2:4], 16) / 255.0,
        "blue": int(value[4:6], 16) / 255.0,
    }


def _generated_sheet_reset_requests(
    sheet_id: int,
    row_count: int,
    column_count: int,
) -> list[dict[str, Any]]:
    """Return requests that remove all legacy template layout from a sheet.

    values.clear() only removes values.  It does *not* remove merged cells or
    user-entered formatting, which is why the former A3:... placeholder blocks
    survived and swallowed later rows.  These requests make every refresh
    idempotent, including for spreadsheets created from older templates.
    """
    full_grid = {
        "sheetId": sheet_id,
        "startRowIndex": 0,
        "endRowIndex": row_count,
        "startColumnIndex": 0,
        "endColumnIndex": column_count,
    }
    return [
        {"unmergeCells": {"range": full_grid}},
        {
            "updateCells": {
                "range": full_grid,
                "fields": "userEnteredFormat",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 0},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]


def _generated_sheet_format_requests(
    sheet_id: int,
    column_count: int,
    column_widths: tuple[int, ...],
) -> list[dict[str, Any]]:
    header_format = {
        "backgroundColor": _hex_to_rgb("#17365D"),
        "textFormat": {
            "bold": True,
            "foregroundColor": _hex_to_rgb("#FFFFFF"),
        },
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "wrapStrategy": "WRAP",
    }
    requests: list[dict[str, Any]] = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": column_count,
                },
                "cell": {"userEnteredFormat": header_format},
                "fields": "userEnteredFormat",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": 38},
                "fields": "pixelSize",
            }
        },
    ]
    for index, width in enumerate(column_widths[:column_count]):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )
    return requests


def _write_table(
    service,
    spreadsheet_id: str,
    title: str,
    sheet_meta: dict[str, int],
    rows: list[list[Any]],
) -> None:
    sheet_id = sheet_meta["sheet_id"]
    grid_rows = sheet_meta["row_count"]
    grid_columns = sheet_meta["column_count"]

    # Remove merged placeholders, fills, borders and frozen rows from older
    # versions before inserting the current output.
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": _generated_sheet_reset_requests(
                sheet_id,
                grid_rows,
                grid_columns,
            )
        },
    ).execute()

    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{title}'!A:Z",
        body={},
    ).execute()

    if not rows:
        return

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{title}'!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()

    used_columns = max(len(row) for row in rows)
    widths = GENERATED_SHEET_COLUMN_WIDTHS.get(
        title,
        tuple(160 for _ in range(used_columns)),
    )
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": _generated_sheet_format_requests(
                sheet_id,
                used_columns,
                widths,
            )
        },
    ).execute()


def write_generated_tabs(
    spreadsheet_id: str,
    sync_status: list[list[Any]],
    team_checklist: list[list[Any]],
    player_summary: list[list[Any]],
) -> None:
    service = create_service()
    titles = ["Sync Status", "Team Checklist", "Player Summary"]
    metadata = _ensure_sheets(service, spreadsheet_id, titles)
    _write_table(service, spreadsheet_id, "Sync Status", metadata["Sync Status"], sync_status)
    _write_table(
        service,
        spreadsheet_id,
        "Team Checklist",
        metadata["Team Checklist"],
        team_checklist,
    )
    _write_table(
        service,
        spreadsheet_id,
        "Player Summary",
        metadata["Player Summary"],
        player_summary,
    )
