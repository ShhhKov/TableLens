# TableLens

A spreadsheet editor for reviewing rows and checking linked sources on Linux, Windows, and macOS. Portable packages include Python 3.13 and the required libraries: users do not need to install Python, Excel, or LibreOffice. Supported platforms: Linux x64/ARM64, Windows x64, and macOS Intel/Apple Silicon.

## Build from source

You need Python 3.13 and internet access to prepare the portable packages. Archives for all platforms can be built on Linux. Run these commands from the project directory:

```sh
python3 packaging/download_runtimes.py
python3 packaging/make_packages.py
```

The output files are `packages/TableLens-Linux.zip`, `packages/TableLens-Windows.zip`, and `packages/TableLens-macOS.zip`. To build only one platform, pass `--platform Linux`, `--platform Windows`, or `--platform macOS`.

The `runtime`, `packages`, and `workspace` directories are excluded from Git. The first two contain generated runtimes and release archives; `workspace` contains user files and progress.

## Launch a portable package

Extract the entire application folder into a writable location. Do not launch files directly from the ZIP archive. Keep `runtime`, `libraries`, `assets`, and the application files together.

| Platform | Launcher |
| --- | --- |
| Linux x64 / ARM64 | `TableLens.desktop` |
| Windows x64 | `Launch.cmd` |
| macOS Intel / Apple Silicon | `Launch.command` |

On Linux, your file manager may ask you to allow the `.desktop` file to run as a program. If it opens as text, run `Launch.sh` instead.

Supported systems include modern 64-bit Linux distributions using glibc, Windows x64, and macOS on Intel and Apple Silicon. Alpine/musl, 32-bit systems, Windows ARM64, Android, and iOS are not currently supported. On macOS, you can also run `sh Launch.command` from a terminal in the application folder.

The application opens in your browser. Keep the terminal window open while using a portable package. The close button in the application header stops the server; Ctrl+C in the terminal also stops it.

## Windows: a single EXE file

An additional Windows build packages Python, the libraries, the interface, and PDF viewing into one `TableLens.exe`. Users do not need to install Python or extract an application folder. Double-clicking the EXE opens the interface in the browser without a console window. The close button in the application header stops the process.

The EXE stores working files and progress in `%LOCALAPPDATA%\TableLens\workspace`, and startup diagnostics in `%LOCALAPPDATA%\TableLens\TableLens.log`. You can move or replace the EXE while keeping your data. Working files are stored separately from the executable and remain after the application closes.

Build on Windows x64 with Python 3.13:

```powershell
python -m pip install -r packaging/windows-build-requirements.txt
python -B packaging/make_windows_exe.py
python -B packaging/verify_windows_exe.py
```

The output is `packages/TableLens.exe`. The **Windows EXE** GitHub Actions workflow builds and tests the executable automatically after application changes are pushed to `main`. You can also start it manually with **Run workflow**. After a successful run, download **TableLens-Windows-exe** from that run's **Artifacts** section and extract `TableLens.exe`.

## Interface language and theme

The interface supports English and Russian. At startup, it uses the device's interface language: Russian for Russian locales, English for all others. The round language button next to the close button shows the language you can switch to: **En** in the Russian interface and **Рус** in the English interface. The same button is available in the file-opening dialog. Switching languages preserves unsaved edits and column settings. Table contents and filenames are never translated.

A round theme button sits beside the language button. The moon switches to the dark theme; the sun switches to the light theme. It is available in both the editor and the file-opening dialog. Each launch starts with the device's theme: GNOME/GTK or KDE preferences on Linux, the app theme on Windows, and appearance preferences on macOS. Browser preferences are used when device settings are unavailable. A manual selection lasts until the next launch and preserves your edits.

## Open a file and configure columns

1. Choose a file using the browser's file picker or select a previously opened file.
2. For a workbook, choose a sheet. If the file has no header row, clear **First row is a header**. For text files, you can select the delimiter and encoding.
3. Set each column to **Edit**, **Read only**, or **Hide**. Column names are unrestricted; empty or duplicate headers are allowed.
4. Enable matching-value review for editable columns where needed. To create a dropdown, enter the allowed values, one per line.
5. Select the visible column used for source searches and click **Start editing**.

Settings are saved per file and sheet. You can change them later using **Columns**.

## File formats

| Input | Output |
| --- | --- |
| TSV, CSV, delimited TXT | Same format and original encoding |
| XLSX, XLSM | Same format, including other sheets |
| ODS | ODS, including other sheets |
| XLS, XLSB | XLSX containing data from all sheets |

TXT delimiters: tab, comma, `;`, or `|`. Encodings: UTF-8, Windows-1251, UTF-16, and Latin-1. Automatic detection tries UTF-8 first, then Windows-1251. Limits: 50 MB per file, 100,000 rows and 1,000 columns per sheet. Password-protected workbooks are not supported.

XLS/XLSB conversion transfers sheet contents; original formatting, formulas, and macros are not reconstructed. XLSX/XLSM retain common styles, formulas, hyperlinks, and VBA in XLSM, but some specialized Excel objects may not survive. Check the output when working with complex workbooks. See the [openpyxl documentation](https://openpyxl.readthedocs.io/en/stable/tutorial.html#saving-a-workbook).

## Edit and review rows

- The confirm button saves the row and moves forward. **Save** saves without moving forward unless a matching-value review is active. Keyboard shortcuts: Ctrl+Enter to confirm; Alt+↑/↓ to navigate; Enter in the row-number field to jump to that row.
- **Skip** postpones a row. **Skipped** provides quick navigation to postponed rows. Confirming a row removes its skipped status.
- Text fields display a visual line break after `;`. This is not written to the file; original spaces and actual line breaks are preserved.
- Changing a value in a column marked for matching-value review starts a sequential review of other rows with exactly the same old value. **Apply** places the suggested value in the field. You can keep the previous value and edit other fields instead. Each row is saved separately; changes are not applied in bulk.
- When the review ends, the editor returns to the next unprocessed row after the original row. The main pass skips rows already confirmed or postponed. Outside a review, you can jump to any row number. Unfinished reviews are restored between launches.

## View sources

### Address bar and shared source

The source pane has an address bar on Linux, Windows, and macOS. Enter an HTTP/HTTPS URL (or a website name, which uses HTTPS) and press Enter or the arrow button to open it, even when the table has no link column. The reload button fetches the page again; back and forward navigate source history. The address bar shows the final address after redirects.

Use the pin button to keep the current HTML page or PDF while switching rows. Search updates using the new row's selected search column. Explicitly clicking a table link still opens that source. Unpinning resumes automatic preview when it is enabled. Opening another document or sheet clears the pin and source history. Pinning applies to the current session.

The top row contains back/forward navigation, the address bar, reload, and pin. Zoom controls sit before the search field in the second row. If automatic search finds no matches, a prominent, dismissible notice explains that this does not mean the item is absent: the website may limit automatic search, so you should check the page manually. See [ROADMAP.md](ROADMAP.md) for the next stages.

### Links and preview controls

Links in visible columns, including Excel/ODS hyperlinks, open in the right pane. Read-only fields display URLs as **Link**. Automatic preview can be turned off.

HTML pages retain styles and scripts and are served through a separate local address, isolated from the editor. Expandable sections work. Navigation stays in the right pane; the back and forward buttons track source history for the current row.

Search uses the selected column's text before the first `|`, ignoring case and whitespace. You can edit the query manually. Matches are highlighted and the first match is scrolled into view. PDF controls navigate through pages and pages containing matches. Zoom ranges from 50% to 300%. Drag the divider to resize the panes; its position is saved. Double-click it to restore the default width.

PDFs without a text layer cannot be searched. Sites requiring authentication, blocking automated requests, or depending on complex external services may work only partially. If needed, copy the address from the address bar and open it directly in your browser. Source files are limited to 40 MB. POST forms are not submitted through the local preview.

## Save and move your work

The original file on your computer is never modified. The selected file is copied into the application's `workspace` directory, or into `%LOCALAPPDATA%\TableLens\workspace` when using the Windows EXE. The result is saved beside that copy as `name.edited.extension`. **Download result** lets you save it to another folder through the browser.

Selecting the same original file again resumes work from the saved result. Other workbook sheets are included in the output. Progress, skipped rows, and settings are stored separately. If an output file existed before the session, the first save creates a `.bak` copy. To move your work, copy the `workspace` directory along with the portable application, or copy it between the EXE's data directories.

## Bundled components

Python: [Astral python-build-standalone](https://github.com/astral-sh/python-build-standalone). Runtime and library versions, sources, and SHA-256 checksums are listed in `BUNDLE_MANIFEST.json`; licenses are preserved in the runtime and library directories. The EXE also includes the bundled library license files.

PDF viewing: [Mozilla PDF.js](https://mozilla.github.io/pdf.js/), with its license in `assets/PDFJS_LICENSE`.
