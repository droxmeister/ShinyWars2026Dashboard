from __future__ import annotations

import unittest

from src.sheets_client import (
    _generated_sheet_format_requests,
    _generated_sheet_reset_requests,
)


class SheetsClientFormattingTests(unittest.TestCase):
    def test_reset_removes_merges_and_all_user_formatting(self):
        requests = _generated_sheet_reset_requests(123, 1000, 26)
        self.assertEqual(requests[0]["unmergeCells"]["range"]["sheetId"], 123)
        self.assertEqual(
            requests[1]["updateCells"]["fields"],
            "userEnteredFormat",
        )
        self.assertEqual(
            requests[2]["updateSheetProperties"]["properties"]["gridProperties"]["frozenRowCount"],
            0,
        )

    def test_output_reapplies_only_header_and_expected_widths(self):
        requests = _generated_sheet_format_requests(321, 2, (260, 240))
        header_request = requests[0]["repeatCell"]
        self.assertEqual(header_request["range"]["endRowIndex"], 1)
        self.assertEqual(header_request["range"]["endColumnIndex"], 2)
        self.assertTrue(
            header_request["cell"]["userEnteredFormat"]["textFormat"]["bold"]
        )
        width_requests = [
            request["updateDimensionProperties"]
            for request in requests
            if "updateDimensionProperties" in request
            and request["updateDimensionProperties"]["range"]["dimension"] == "COLUMNS"
        ]
        self.assertEqual([request["properties"]["pixelSize"] for request in width_requests], [260, 240])


if __name__ == "__main__":
    unittest.main()
