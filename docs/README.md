# Documentation build

`phantom-pj-alerts-documentation.pdf` is generated, not hand-edited. To change it,
edit the content in `build.py` or the diagrams in `diagrams.py`, then:

    python3 -c "import base64,pathlib; pathlib.Path('logo.b64').write_text(base64.b64encode(pathlib.Path('logo.png').read_bytes()).decode())"
    python3 build.py
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
      --no-pdf-header-footer --print-to-pdf="$PWD/phantom-pj-alerts-documentation.pdf" \
      "file://$PWD/doc.html"

`figs.py` holds the shared SVG drawing helpers so every diagram uses the same
visual language. Diagrams are hand-placed SVG, so if you move a box, check the
arrows still clear it.
