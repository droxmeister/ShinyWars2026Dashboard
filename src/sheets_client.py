"""Google Sheets I/O for the Shiny Wars dashboard."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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


def _sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
        .execute()
    )
    return {
        str(sheet["properties"]["title"])
        for sheet in metadata.get("sheets", [])
    }


def _ensure_sheets(service, spreadsheet_id: str, titles: Iterable[str]) -> None:
    existing = _sheet_titles(service, spreadsheet_id)
    requests = [
        {"addSheet": {"properties": {"title": title}}}
        for title in titles
        if title not in existing
    ]
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()


def _write_table(service, spreadsheet_id: str, title: str, rows: list[list[Any]]) -> None:
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{title}'!A:Z",
        body={},
    ).execute()
    if rows:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()


def write_generated_tabs(
    spreadsheet_id: str,
    sync_status: list[list[Any]],
    team_checklist: list[list[Any]],
    player_summary: list[list[Any]],
) -> None:
    service = create_service()
    titles = ["Sync Status", "Team Checklist", "Player Summary"]
    _ensure_sheets(service, spreadsheet_id, titles)
    _write_table(service, spreadsheet_id, "Sync Status", sync_status)
    _write_table(service, spreadsheet_id, "Team Checklist", team_checklist)
    _write_table(service, spreadsheet_id, "Player Summary", player_summary)
