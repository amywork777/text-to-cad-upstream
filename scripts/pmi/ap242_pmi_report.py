"""CLI for the independent AP242 semantic PMI reader shipped with cadgen."""
from cadgen._internal.ap242_pmi_report import main, report

if __name__ == "__main__":
    raise SystemExit(main())
