"""ConvertAll: convert, compress or extract any file.

    from convertall import convert, plan, Report
    report = Report()
    out = convert("photo.heic", "jpg", report=report, options={"quality": 80})
    print(report.notes, report.warnings)
"""

__version__ = "1.2.0"

__all__ = ["Report", "__version__", "convert", "extract", "plan"]


def __getattr__(name: str):
    # loaded on first use, so starting the window or handing it files doesn't load the converters
    if name == "Report":
        from .assurance import Report
        return Report
    if name in ("convert", "extract", "plan"):
        from . import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module 'convertall' has no attribute {name!r}")
