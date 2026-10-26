"""GPS and map files: GPX, KML, KMZ and GeoJSON to each other, and a table of points (CSV).
Standard library only: everything is read into one small model of waypoints and lines."""

import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter

MAPS = {"gpx", "kml", "kmz", "geojson"}


@dataclass
class Point:
    lat: float
    lon: float
    ele: float | None = None
    time: str = ""  # ISO 8601, as the file had it
    name: str = ""
    desc: str = ""


@dataclass
class Line:
    name: str = ""
    kind: str = "track"  # track, route, or area (a closed outline)
    segments: list[list[Point]] = field(default_factory=list)
    desc: str = ""


@dataclass
class Map:
    name: str = ""
    points: list[Point] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name: str):
    return next((c for c in el if _local(c.tag) == name), None)


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name: str) -> str:
    c = _child(el, name)
    return (c.text or "").strip() if c is not None else ""


def _float(s) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _parse_xml(data: bytes):
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ConversionError(f"This file isn't valid XML: {exc}") from None


# ---- GPX

def _gpx_point(el) -> Point | None:
    lat, lon = _float(el.get("lat")), _float(el.get("lon"))
    if lat is None or lon is None:
        return None
    return Point(lat, lon, _float(_text(el, "ele")), _text(el, "time"), _text(el, "name"), _text(el, "desc"))


def read_gpx(data: bytes) -> Map:
    root = _parse_xml(data)
    if _local(root.tag) != "gpx":
        raise ConversionError("Not a GPX file")
    meta = _child(root, "metadata")
    m = Map(_text(meta, "name") if meta is not None else "")
    m.points = [p for p in map(_gpx_point, _children(root, "wpt")) if p]
    for rte in _children(root, "rte"):
        pts = [p for p in map(_gpx_point, _children(rte, "rtept")) if p]
        m.lines.append(Line(_text(rte, "name"), "route", [pts], _text(rte, "desc")))
    for trk in _children(root, "trk"):
        segs = [[p for p in map(_gpx_point, _children(seg, "trkpt")) if p] for seg in _children(trk, "trkseg")]
        m.lines.append(Line(_text(trk, "name"), "track", [s for s in segs if s], _text(trk, "desc")))
    return m


def write_gpx(m: Map) -> bytes:
    ns = "http://www.topografix.com/GPX/1/1"
    root = ET.Element("gpx", {"version": "1.1", "creator": "ConvertAll", "xmlns": ns})
    if m.name:
        ET.SubElement(ET.SubElement(root, "metadata"), "name").text = m.name

    def point(parent, tag: str, p: Point) -> None:
        el = ET.SubElement(parent, tag, {"lat": f"{p.lat:.7f}", "lon": f"{p.lon:.7f}"})
        if p.ele is not None:
            ET.SubElement(el, "ele").text = f"{p.ele:g}"
        if p.time:
            ET.SubElement(el, "time").text = p.time
        if p.name:
            ET.SubElement(el, "name").text = p.name
        if p.desc:
            ET.SubElement(el, "desc").text = p.desc

    for p in m.points:
        point(root, "wpt", p)
    for line in m.lines:
        if line.kind == "route":
            rte = ET.SubElement(root, "rte")
            if line.name:
                ET.SubElement(rte, "name").text = line.name
            for p in (p for seg in line.segments for p in seg):
                point(rte, "rtept", p)
        else:  # tracks, and outlines drawn as a track
            trk = ET.SubElement(root, "trk")
            if line.name:
                ET.SubElement(trk, "name").text = line.name
            if line.desc:
                ET.SubElement(trk, "desc").text = line.desc
            for seg in line.segments:
                s = ET.SubElement(trk, "trkseg")
                for p in seg:
                    point(s, "trkpt", p)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---- KML / KMZ

def _kml_coords(text: str) -> list[Point]:
    pts = []
    for tup in (text or "").split():
        parts = tup.split(",")
        lon, lat = _float(parts[0]), _float(parts[1]) if len(parts) > 1 else None
        if lon is not None and lat is not None:
            pts.append(Point(lat, lon, _float(parts[2]) if len(parts) > 2 else None))
    return pts


def _kml_geometries(el, name: str, desc: str, m: Map, line: Line | None = None) -> None:
    for g in el:
        tag = _local(g.tag)
        if tag == "Point":
            for p in _kml_coords(_text(g, "coordinates"))[:1]:
                p.name, p.desc = name, desc
                m.points.append(p)
        elif tag in ("LineString", "LinearRing", "Polygon", "Track"):
            if line is None:
                line = Line(name, "track", [], desc)
                m.lines.append(line)
            if tag == "LineString":
                line.segments.append(_kml_coords(_text(g, "coordinates")))
            elif tag == "LinearRing":
                line.kind = "area"
                line.segments.append(_kml_coords(_text(g, "coordinates")))
            elif tag == "Polygon":
                line.kind = "area"
                outer = _child(g, "outerBoundaryIs")
                ring = _child(outer, "LinearRing") if outer is not None else None
                if ring is not None:
                    line.segments.append(_kml_coords(_text(ring, "coordinates")))
            else:  # gx:Track: <when> times and <gx:coord> "lon lat alt" in step
                whens = [(w.text or "").strip() for w in _children(g, "when")]
                pts = []
                for i, c in enumerate(_children(g, "coord")):
                    parts = (c.text or "").split()
                    if len(parts) >= 2:
                        pts.append(Point(float(parts[1]), float(parts[0]),
                                         _float(parts[2]) if len(parts) > 2 else None,
                                         whens[i] if i < len(whens) else ""))
                line.segments.append(pts)
        elif tag in ("MultiGeometry", "MultiTrack"):
            _kml_geometries(g, name, desc, m, line)


def read_kml(data: bytes) -> Map:
    root = _parse_xml(data)
    if _local(root.tag) != "kml":
        raise ConversionError("Not a KML file")
    doc = next((e for e in root.iter() if _local(e.tag) in ("Document", "Folder")), root)
    m = Map(_text(doc, "name"))
    for pm in (e for e in root.iter() if _local(e.tag) == "Placemark"):
        _kml_geometries(pm, _text(pm, "name"), _text(pm, "description"), m)
    m.lines = [line for line in m.lines if any(line.segments)]
    return m


def write_kml(m: Map) -> bytes:
    root = ET.Element("kml", {"xmlns": "http://www.opengis.net/kml/2.2"})
    doc = ET.SubElement(root, "Document")
    ET.SubElement(doc, "name").text = m.name or "ConvertAll"
    style = ET.SubElement(doc, "Style", {"id": "line"})
    ls = ET.SubElement(style, "LineStyle")
    ET.SubElement(ls, "color").text = "ff0000ff"  # aabbggrr: red
    ET.SubElement(ls, "width").text = "3"
    ET.SubElement(ET.SubElement(style, "PolyStyle"), "color").text = "400000ff"

    def coords(pts: list[Point]) -> str:
        return " ".join(f"{p.lon:.7f},{p.lat:.7f}" + (f",{p.ele:g}" if p.ele is not None else "") for p in pts)

    def placemark(name: str, desc: str):
        pm = ET.SubElement(doc, "Placemark")
        if name:
            ET.SubElement(pm, "name").text = name
        if desc:
            ET.SubElement(pm, "description").text = desc
        return pm

    for p in m.points:
        pm = placemark(p.name, p.desc)
        if p.time:
            ET.SubElement(ET.SubElement(pm, "TimeStamp"), "when").text = p.time
        ET.SubElement(ET.SubElement(pm, "Point"), "coordinates").text = coords([p])
    for line in m.lines:
        pm = placemark(line.name, line.desc)
        ET.SubElement(pm, "styleUrl").text = "#line"
        segs = [s for s in line.segments if s]
        parent = ET.SubElement(pm, "MultiGeometry") if len(segs) > 1 else pm
        for seg in segs:
            if line.kind == "area":
                ring = ET.SubElement(ET.SubElement(ET.SubElement(parent, "Polygon"), "outerBoundaryIs"), "LinearRing")
                ET.SubElement(ring, "coordinates").text = coords(seg + seg[:1] if seg[0] != seg[-1] else seg)
            else:
                ET.SubElement(ET.SubElement(parent, "LineString"), "coordinates").text = coords(seg)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def read_kmz(src: Path) -> Map:
    try:
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ConversionError("No KML inside this KMZ")
            main = "doc.kml" if "doc.kml" in names else names[0]
            return read_kml(z.read(main))
    except zipfile.BadZipFile as exc:
        raise ConversionError(f"Not a KMZ file: {exc}") from None


# ---- GeoJSON

def _gj_points(coords, times=None) -> list[Point]:
    pts = []
    for i, c in enumerate(coords or []):
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            pts.append(Point(float(c[1]), float(c[0]), _float(c[2]) if len(c) > 2 else None,
                             str(times[i]) if times and i < len(times) else ""))
    return pts


def read_geojson(data: bytes) -> Map:
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConversionError(f"Not a GeoJSON file: {exc}") from None
    m = Map(obj.get("name", "") if isinstance(obj, dict) else "")
    features = obj.get("features", []) if obj.get("type") == "FeatureCollection" else [obj]
    for f in features:
        if not isinstance(f, dict):
            continue
        props = (f.get("properties") or {}) if f.get("type") == "Feature" else {}
        geom = f.get("geometry") if f.get("type") == "Feature" else f
        name, desc = str(props.get("name", "")), str(props.get("desc", props.get("description", "")))
        times = props.get("coordTimes") or props.get("times")
        geoms = geom.get("geometries", []) if geom and geom.get("type") == "GeometryCollection" else [geom]
        line = None
        for g in (g for g in geoms if isinstance(g, dict)):
            kind, c = g.get("type"), g.get("coordinates")
            if kind in ("Point", "MultiPoint"):
                for p in _gj_points([c] if kind == "Point" else c):
                    p.name, p.desc, p.time = name, desc, str(props.get("time", ""))
                    m.points.append(p)
                continue
            if line is None:
                line = Line(name, "track", [], desc)
                m.lines.append(line)
            if kind == "LineString":
                line.segments.append(_gj_points(c, times))
            elif kind == "MultiLineString":
                for i, seg in enumerate(c or []):
                    seg_times = times[i] if times and i < len(times) and isinstance(times[i], list) else None
                    line.segments.append(_gj_points(seg, seg_times))
            elif kind in ("Polygon", "MultiPolygon"):
                line.kind = "area"
                for poly in ([c] if kind == "Polygon" else c or []):
                    if poly:
                        line.segments.append(_gj_points(poly[0]))  # the outer ring
    m.lines = [line for line in m.lines if any(line.segments)]
    return m


def write_geojson(m: Map) -> bytes:
    def pos(p: Point) -> list:
        return [round(p.lon, 7), round(p.lat, 7)] + ([p.ele] if p.ele is not None else [])

    features = []
    for p in m.points:
        props = {k: v for k, v in (("name", p.name), ("desc", p.desc), ("time", p.time)) if v}
        features.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": pos(p)}})
    for line in m.lines:
        segs = [s for s in line.segments if s]
        props = {k: v for k, v in (("name", line.name), ("desc", line.desc)) if v}
        props["kind"] = line.kind
        if line.kind == "area":
            geom = {"type": "MultiPolygon" if len(segs) > 1 else "Polygon",
                    "coordinates": [[[pos(p) for p in s + s[:1]]] for s in segs] if len(segs) > 1
                    else [[pos(p) for p in segs[0] + segs[0][:1]]]}
        elif len(segs) == 1:
            geom = {"type": "LineString", "coordinates": [pos(p) for p in segs[0]]}
            if any(p.time for p in segs[0]):
                props["coordTimes"] = [p.time for p in segs[0]]
        else:
            geom = {"type": "MultiLineString", "coordinates": [[pos(p) for p in s] for s in segs]}
            if any(p.time for s in segs for p in s):
                props["coordTimes"] = [[p.time for p in s] for s in segs]
        features.append({"type": "Feature", "properties": props, "geometry": geom})
    return (json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=1)
            + "\n").encode("utf-8")


# ---- table of points

def write_csv(m: Map) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["type", "name", "segment", "latitude", "longitude", "elevation", "time", "description"])
    for p in m.points:
        w.writerow(["waypoint", p.name, "", p.lat, p.lon, "" if p.ele is None else p.ele, p.time, p.desc])
    for line in m.lines:
        for i, seg in enumerate(line.segments, 1):
            for p in seg:
                w.writerow([line.kind, line.name, i, p.lat, p.lon, "" if p.ele is None else p.ele, p.time, ""])
    return out.getvalue().encode("utf-8")


def read_map(src: Path, fmt: str) -> Map:
    if fmt == "kmz":
        m = read_kmz(src)
    else:
        m = {"gpx": read_gpx, "kml": read_kml, "geojson": read_geojson}[fmt](src.read_bytes())
    if not m.points and not m.lines:
        raise ConversionError("No places or tracks found in this file")
    return m


@converter(inputs=MAPS, outputs=MAPS | {"csv"})
def map_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    m = read_map(src, src_fmt)
    if dst_fmt == "kmz":
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.kml", write_kml(m))
        return
    dst.write_bytes({"gpx": write_gpx, "kml": write_kml, "geojson": write_geojson, "csv": write_csv}[dst_fmt](m))
