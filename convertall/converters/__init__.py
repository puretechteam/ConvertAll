# Importing a module registers its converters. Engine-free modules come first so
# they win ties against engine-backed routes of equal cost.
from . import images, pdf, data, fonts, archives, comics, markup, models, cad, medical  # noqa: F401
from . import media, subtitles, documents, ebooks, magick  # noqa: F401
