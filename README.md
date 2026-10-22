# TableLens

A spreadsheet editor for reviewing table rows one by one and checking them against linked web pages and PDFs. Portable packages include Python 3.13 and all required libraries: Python, Excel, and LibreOffice do not need to be installed.

Supported: 64-bit Linux with glibc (x64, ARM64), Windows x64, and macOS (Intel, Apple Silicon). Not supported: Alpine/musl, 32-bit systems, Windows ARM64, Android, and iOS.

## Launch

Extract the whole application folder to a writable location; do not run it from inside the ZIP archive. Keep `runtime`, `libraries`, `assets`, and the application files together.

| Platform | Launcher |
| --- | --- |
| Linux | `TableLens.desktop` (or `Launch.sh` if the file manager opens it as text) |
| Windows | `Launch.cmd` |
| macOS | `Launch.command` (or `sh Launch.command` in a terminal) |

The application opens in your browser. Keep the terminal window open while you work. To stop the application, use the close button in the header or press Ctrl+C in the terminal.

### Windows: single EXE

`TableLens.exe` contains Python, the libraries, the interface, and the PDF viewer in one file. Double-click it; no console window opens. Working files and progress are stored in `%LOCALAPPDATA%\TableLens\workspace` and startup diagnostics in `%LOCALAPPDATA%\TableLens\TableLens.log`, so you can move or replace the EXE without losing data.

## Open a file

1. Choose a file in the browser's file picker or pick a previously opened file.
2. For a workbook, choose a sheet. For text files, choose the delimiter and encoding if automatic detection is wrong. Clear **First row is a header** if the file has no header row.
3. Set each column to **Edit**, **Read only**, or **Hide**. Empty and duplicate headers are allowed.
4. Optionally enable matching-value review for editable columns, or turn a column into a dropdown by entering allowed values, one per line.
5. Select the column used for source searches and click **Start editing**.

Settings are saved per file and sheet and can be changed later with **Columns**.

## File formats

| Input | Output |
| --- | --- |
| TSV, CSV, delimited TXT | Same format and original encoding |
| XLSX, XLSM | Same format, including other sheets |
| ODS | ODS, including other sheets |
| XLS, XLSB | XLSX with data from all sheets |

- TXT delimiters: tab, comma, `;`, `|`. Encodings: UTF-8, Windows-1251, UTF-16, Latin-1; automatic detection tries UTF-8, then Windows-1251.
- Limits: 50 MB per file, 100,000 rows and 1,000 columns per sheet. Password-protected workbooks are not supported.
- XLS/XLSB conversion keeps cell contents only, without formatting, formulas, or macros. XLSX/XLSM keep common styles, formulas, hyperlinks, and VBA, but some specialized Excel objects may be lost (see the [openpyxl documentation](https://openpyxl.readthedocs.io/en/stable/tutorial.html#saving-a-workbook)). Check the result for complex workbooks.

## Edit rows

- **Confirm** saves the row and moves to the next one. **Save** saves without moving. **Skip** postpones a row; **Skipped** lists postponed rows.
- Shortcuts: Ctrl+Enter confirms, Alt+↑/↓ navigates, Enter in the row-number field jumps to that row.
- Text fields show a visual line break after `;`. It is not written to the file; real spaces and line breaks are preserved.
- Changing a value in a column with matching-value review starts a review of other rows with the same old value. **Apply** inserts the new value; each row is saved separately, never in bulk. When the review ends, editing continues from the next unprocessed row. Unfinished reviews are restored after restart.

## View sources

Links in visible columns, including Excel/ODS hyperlinks, open in the right pane. Read-only fields show URLs as **Link**. Automatic preview can be turned off.

- **Address bar**: enter an HTTP/HTTPS address or a site name to open any page, even if the table has no link column. Back, forward, and reload work as in a browser; the bar shows the final address after redirects.
- **Pin**: keeps the current page or PDF while you switch rows; the search updates for each new row. Clicking a table link still opens that link. The pin is cleared when you open another document or sheet.
- **Search** uses the selected column's text before the first `|`, ignoring case and whitespace. You can edit the query. Matches are highlighted and the first one is scrolled into view; for PDFs you can jump between pages with matches. If nothing is found, a notice reminds you to check the page manually — sites may limit automatic search.
- Zoom: 50–300%. Drag the divider to resize the panes; double-click it to reset.

HTML pages keep their styles and scripts and run on a separate local address, isolated from the editor. Limitations: sources up to 40 MB; PDFs without a text layer cannot be searched; POST forms are not submitted; sites that require sign-in or block automated requests may work partially — open them in your browser from the address bar.

## Save and move your work

The original file is never modified. It is copied into `workspace` (or the EXE's data directory), and the result is saved next to the copy as `name.edited.extension`. **Download result** saves it to another folder. Opening the same file again resumes work. If a result file already existed before the session, the first save creates a `.bak` copy of it. To move your work, copy the `workspace` directory.

## Language and theme

The interface is in English or Russian, chosen from the system language at startup. The round **En**/**Рус** button switches the language, and the sun/moon button switches the theme; both keep unsaved edits. Each launch starts with the system theme. Table contents and file names are never translated.

## Build from source

Requires Python 3.13 and internet access. Archives for all platforms are built on Linux:

```sh
python3 packaging/download_runtimes.py
python3 packaging/make_packages.py            # or --platform Linux|Windows|macOS
```

Output: `packages/TableLens-Linux.zip`, `packages/TableLens-Windows.zip`, `packages/TableLens-macOS.zip`.

The EXE is built on Windows x64 with Python 3.13:

```powershell
python -m pip install -r packaging/windows-build-requirements.txt
python -B packaging/make_windows_exe.py
python -B packaging/verify_windows_exe.py
```

Output: `packages/TableLens.exe`. The **Windows EXE** GitHub Actions workflow builds and tests it on every push to `main` (or manually via **Run workflow**); download it from the run's **Artifacts** as **TableLens-Windows-exe**.

`runtime`, `packages`, and `workspace` are not stored in Git: they contain generated runtimes, release archives, and user data.

See [ROADMAP.md](ROADMAP.md) for planned features.

## Bundled components

- Python: [Astral python-build-standalone](https://github.com/astral-sh/python-build-standalone). Versions, sources, and SHA-256 checksums are listed in `BUNDLE_MANIFEST.json`; licenses are kept in the runtime and library directories.
- PDF viewing: [Mozilla PDF.js](https://mozilla.github.io/pdf.js/), license in `assets/PDFJS_LICENSE`.
