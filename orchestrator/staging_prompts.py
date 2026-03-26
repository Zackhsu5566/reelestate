"""Room-specific staging prompts for virtual staging (v2).

Structured prompt format optimized for nano-banana-2/edit:
  [KEEP EXACTLY] / [EDIT ONLY] / style spec blocks / [DO NOT]

Each style has a generic (fallback) prompt and room-specific prompts.
"""

from __future__ import annotations

# ── Room name mapping ──
# Maps Chinese space names to canonical room type keys.

_ROOM_NAME_MAP: dict[str, str] = {
    # ── 廚房 ──
    "廚房": "kitchen",
    "kitchen": "kitchen",
    # ── 客廳 ──
    "客廳": "living_room",
    "起居室": "living_room",
    "living": "living_room",
    # ── 臥室 ──
    "臥室": "bedroom",
    "臥房": "bedroom",
    "主臥": "bedroom",
    "次臥": "bedroom",
    "兒童房": "bedroom",
    "小孩房": "bedroom",
    "嬰兒房": "bedroom",
    "客房": "bedroom",
    "房間": "bedroom",
    "bedroom": "bedroom",
    # ── 浴室 ──
    "浴室": "bathroom",
    "廁所": "bathroom",
    "衛浴": "bathroom",
    "洗手間": "bathroom",
    "化妝室": "bathroom",
    "bathroom": "bathroom",
    "toilet": "bathroom",
    # ── 餐廳 ──
    "餐廳": "dining_room",
    "飯廳": "dining_room",
    "dining": "dining_room",
    # ── 書房 ──
    "書房": "home_office",
    "工作室": "home_office",
    "辦公": "home_office",
    "office": "home_office",
    "study": "home_office",
    # ── 玄關 ──
    "玄關": "entryway",
    "門廳": "entryway",
    "entryway": "entryway",
    "entry": "entryway",
}


def _classify_room(space_name: str) -> str | None:
    """Map a space name to a canonical room type key.

    Supports Chinese and English keywords, case-insensitive for English.
    """
    name_lower = space_name.lower()
    for keyword, room_type in _ROOM_NAME_MAP.items():
        if keyword in name_lower:
            return room_type
    return None


# ═══════════════════════════════════════════
# 1. Japanese Muji / Japandi
# ═══════════════════════════════════════════

_MUJI_GENERIC = """\
Apply Japanese Muji / Japandi interior style.

[KEEP EXACTLY]
- room layout, walls, windows, doors, ceiling
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style and placement
- materials, colors, textures
- decorative objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural linen, cotton

[COLORS]
- white, beige, light brown, warm grey

[TEXTURES]
- clean, minimal, natural grain, matte finishes

[FURNITURE]
- low-profile, simple lines
- light wood frames

[DECOR]
- minimal, zen-inspired
- no clutter

[DO NOT]
- change room layout or structure
- move or resize windows/doors
- change camera perspective
- redesign the space

Photorealistic interior photography."""

_MUJI_ROOMS: dict[str, str] = {
    "kitchen": """\
Apply Japanese Muji / Japandi style to this kitchen.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- cabinet style and material
- countertop material
- hardware
- surface objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- matte white or light stone countertop

[COLORS]
- white, beige, light brown

[HARDWARE]
- simple pulls, matte black or brushed nickel

[SURFACES]
- clean and uncluttered
- minimal ceramic dishware only

[DO NOT]
- change room layout or structure
- change camera perspective
- add or remove windows/doors

Photorealistic interior photography.""",

    "living_room": """\
Apply Japanese Muji / Japandi style to this living room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- materials, colors, textures
- decorative objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural linen, cotton upholstery

[COLORS]
- white, beige, warm grey, light brown

[FURNITURE]
- low-profile sofa, simple lines
- light wood coffee table, clean edges

[DECOR]
- minimal: one ceramic vase or a few books
- no clutter

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bedroom": """\
Apply Japanese Muji / Japandi style to this bedroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- bed frame and bedding
- furniture style
- decorative objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural cotton, linen bedding

[COLORS]
- white, beige, soft grey, light brown

[BEDDING]
- simple, neutral solid tones
- no patterns

[FURNITURE]
- low platform bed frame in light wood
- minimal nightstands

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bathroom": """\
Apply Japanese Muji / Japandi style to this bathroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- vanity and storage style
- fixtures
- accessories

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural stone, matte ceramic

[COLORS]
- white, beige, warm grey, light brown

[FIXTURES]
- simple, rounded forms
- matte black or brushed nickel

[ACCESSORIES]
- white cotton towels, neatly folded
- minimal, clean

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "dining_room": """\
Apply Japanese Muji / Japandi style to this dining room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- dining furniture style
- materials, colors
- decorative objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural linen

[COLORS]
- white, beige, warm grey, light brown

[FURNITURE]
- simple wood dining table and chairs
- clean form, no ornamentation

[DECOR]
- minimal: single ceramic bowl or small plant

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "home_office": """\
Apply Japanese Muji / Japandi style to this home office.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- desk and chair style
- shelving
- accessories

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural paper, linen

[COLORS]
- white, beige, warm grey, light brown

[FURNITURE]
- clean-lined desk in light wood
- simple task chair

[ACCESSORIES]
- minimal, functional, uncluttered
- simple desk lamp, one small plant

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "entryway": """\
Apply Japanese Muji / Japandi style to this entryway.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- decorative objects

[WALLS]
- clean matte white or warm beige paint
- remove any existing wallpaper

[MATERIALS]
- light wood: oak, ash
- natural stone

[COLORS]
- white, beige, warm grey, light brown

[FURNITURE]
- slim console or floating shelf in light wood
- simple wall hooks in matte black

[DECOR]
- minimal, functional
- small mirror, one plant

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",
}

# ═══════════════════════════════════════════
# 2. Scandinavian
# ═══════════════════════════════════════════

_SCANDI_GENERIC = """\
Apply Scandinavian interior style.

[KEEP EXACTLY]
- room layout, walls, windows, doors, ceiling
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style and placement
- materials, colors, textures
- decorative objects

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- wool, cotton, natural fabrics

[COLORS]
- white, light grey, soft pastels, warm wood tones

[TEXTURES]
- cozy textiles, soft rug, knit throw
- natural grain, matte finishes

[FURNITURE]
- simple modern, slightly rounded edges
- functional and clean

[DECOR]
- indoor plants, candles
- soft lighting, lived-in warmth
- no clutter

[DO NOT]
- change room layout or structure
- move or resize windows/doors
- change camera perspective
- redesign the space

Photorealistic interior photography."""

_SCANDI_ROOMS: dict[str, str] = {
    "kitchen": """\
Apply Scandinavian style to this kitchen.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- cabinet style and material
- countertop material
- hardware
- surface objects

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- matte laminate

[COLORS]
- white, light grey, soft wood tones

[HARDWARE]
- simple handles, matte black or brushed steel

[DECOR]
- small indoor plant
- textile dish towel

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "living_room": """\
Apply Scandinavian style to this living room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- materials, colors, textures
- decorative objects

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- wool, cotton upholstery

[COLORS]
- white, light grey, soft blue, warm wood

[FURNITURE]
- simple modern sofa, rounded edges
- light wood coffee table

[DECOR]
- indoor plants, candles
- soft rug, knit throw blanket
- cozy but uncluttered

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bedroom": """\
Apply Scandinavian style to this bedroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- bed frame and bedding
- furniture style
- decorative objects

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- cotton, wool bedding

[COLORS]
- white, light grey, soft pastels, warm wood

[BEDDING]
- layered whites and greys
- textured fabrics, knit throw

[DECOR]
- small plant
- warm bedside lamp
- soft rug

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bathroom": """\
Apply Scandinavian style to this bathroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- vanity and storage style
- fixtures
- accessories

[WALLS]
- clean white paint
- remove any existing wallpaper

[MATERIALS]
- light wood: birch
- white ceramic, natural stone

[COLORS]
- white, light grey, warm wood accents

[FIXTURES]
- simple, functional
- chrome or matte black

[ACCESSORIES]
- woven basket, small plant
- cotton towels

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "dining_room": """\
Apply Scandinavian style to this dining room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- dining furniture style
- materials, colors
- decorative objects

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- natural linen

[COLORS]
- white, light grey, warm wood tones

[FURNITURE]
- simple wood dining table and chairs
- soft fabric seats

[DECOR]
- candles, linen table runner
- indoor plant

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "home_office": """\
Apply Scandinavian style to this home office.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- desk and chair style
- shelving
- accessories

[WALLS]
- clean white paint
- optional light grey accent wall
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- wool, cotton

[COLORS]
- white, light grey, warm wood accents

[FURNITURE]
- simple wood desk
- functional chair

[ACCESSORIES]
- functional organizers
- small plant, warm desk lamp
- clutter-free but lived-in

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "entryway": """\
Apply Scandinavian style to this entryway.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- decorative objects

[WALLS]
- clean white paint
- remove any existing wallpaper

[MATERIALS]
- light wood: birch, pine
- natural fiber

[COLORS]
- white, light grey, warm wood

[FURNITURE]
- simple bench or shelf in light wood
- wall hooks in matte black

[DECOR]
- woven basket, small mirror
- small plant, textile runner

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",
}

# ═══════════════════════════════════════════
# 3. Modern Minimalist
# ═══════════════════════════════════════════

_MODERN_GENERIC = """\
Apply modern minimalist interior style.

[KEEP EXACTLY]
- room layout, walls, windows, doors, ceiling
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style and placement
- materials, colors, textures
- decorative objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- glass, metal, polished concrete
- lacquer, engineered surfaces

[COLORS]
- white, grey, black
- monochrome palette

[TEXTURES]
- sleek, smooth, polished
- matte-and-gloss contrast

[FURNITURE]
- clean geometric lines, low-profile
- sharp edges, minimal form

[DECOR]
- absolute minimum
- no clutter on any surface

[DO NOT]
- change room layout or structure
- move or resize windows/doors
- change camera perspective
- redesign the space

Photorealistic interior photography."""

_MODERN_ROOMS: dict[str, str] = {
    "kitchen": """\
Apply modern minimalist style to this kitchen.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- cabinet style and material
- countertop material
- hardware
- surface objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- matte lacquer cabinets
- engineered stone countertop
- stainless steel accents

[COLORS]
- white, grey, black accents

[HARDWARE]
- handleless or slim bar handles
- matte black

[SURFACES]
- completely clean and uncluttered

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "living_room": """\
Apply modern minimalist style to this living room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- materials, colors, textures
- decorative objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- glass, metal, polished concrete
- leather upholstery

[COLORS]
- white, grey, black, monochrome

[FURNITURE]
- clean geometric lines, low-profile
- sharp modern forms

[DECOR]
- absolute minimum
- reduce decoration to single statement piece

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bedroom": """\
Apply modern minimalist style to this bedroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- bed frame and bedding
- furniture style
- decorative objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- lacquer, metal, engineered surfaces
- crisp cotton bedding

[COLORS]
- white, grey, charcoal, black accents

[BEDDING]
- solid color, no patterns
- clean crisp edges

[FURNITURE]
- geometric bed frame
- bare nightstands with minimal objects

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bathroom": """\
Apply modern minimalist style to this bathroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- vanity and storage style
- fixtures
- accessories

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- engineered stone, glass, metal
- large-format tile

[COLORS]
- white, grey, black accents

[FIXTURES]
- geometric, wall-mounted
- matte black or chrome

[ACCESSORIES]
- frameless glass elements
- clean lines, no visible clutter

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "dining_room": """\
Apply modern minimalist style to this dining room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- dining furniture style
- materials, colors
- decorative objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- glass, metal, lacquer
- engineered stone

[COLORS]
- white, grey, black, monochrome

[FURNITURE]
- clean geometric dining table and chairs
- no ornamentation

[DECOR]
- minimal tableware
- no centerpiece clutter

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "home_office": """\
Apply modern minimalist style to this home office.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- desk and chair style
- shelving
- accessories

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- glass, metal, lacquer
- engineered surfaces

[COLORS]
- white, grey, black

[FURNITURE]
- sleek desk, geometric chair
- hidden storage

[ACCESSORIES]
- absolute minimum visible
- cables invisible, clean desktop

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "entryway": """\
Apply modern minimalist style to this entryway.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- decorative objects

[WALLS]
- smooth white or light grey paint
- no texture, no wallpaper

[MATERIALS]
- metal, glass, lacquer
- engineered stone

[COLORS]
- white, grey, black

[FURNITURE]
- single statement piece only
- hidden storage

[DECOR]
- completely uncluttered
- one minimal element maximum

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",
}

# ═══════════════════════════════════════════
# 4. Modern Luxury
# ═══════════════════════════════════════════

_LUXURY_GENERIC = """\
Apply modern luxury interior style.

[KEEP EXACTLY]
- room layout, walls, windows, doors, ceiling
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style and placement
- materials, colors, textures
- decorative objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- marble, dark wood, velvet
- premium leather, brushed gold/brass

[COLORS]
- cream, black, gold accents
- deep green or navy as accent

[TEXTURES]
- polished, layered, rich
- glossy-and-matte contrast

[FURNITURE]
- elegant silhouettes, refined upholstery
- statement pieces

[DECOR]
- statement lighting
- art pieces, layered cushions
- sophisticated but not cluttered

[DO NOT]
- change room layout or structure
- move or resize windows/doors
- change camera perspective
- redesign the space

Photorealistic interior photography."""

_LUXURY_ROOMS: dict[str, str] = {
    "kitchen": """\
Apply modern luxury style to this kitchen.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- cabinet style and material
- countertop material
- hardware
- surface objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- marble countertop
- dark wood cabinets
- brushed gold hardware

[COLORS]
- white, black, gold accents, cream

[HARDWARE]
- brushed gold or brass handles

[DECOR]
- under-cabinet lighting effect
- statement backsplash

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "living_room": """\
Apply modern luxury style to this living room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- materials, colors, textures
- decorative objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- marble, velvet, premium leather
- dark wood, brass accents

[COLORS]
- cream, black, gold
- deep green or navy accents

[FURNITURE]
- elegant silhouettes
- refined velvet or leather upholstery

[DECOR]
- statement lighting fixture
- art pieces, layered cushions

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bedroom": """\
Apply modern luxury style to this bedroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- bed frame and bedding
- furniture style
- decorative objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- velvet, silk, dark wood
- marble, brass accents

[COLORS]
- cream, gold, charcoal
- deep jewel tone accents

[BEDDING]
- plush, layered textures
- tufted headboard feel

[DECOR]
- statement bedside lamps
- art above bed, curtain drapes

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bathroom": """\
Apply modern luxury style to this bathroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- vanity and storage style
- fixtures
- accessories

[WALLS]
- elegant matte cream or white paint
- remove any existing wallpaper

[MATERIALS]
- marble, natural stone
- brass, dark wood accents

[COLORS]
- white, cream, gold, black accents

[FIXTURES]
- brushed gold or brass
- elegant forms

[ACCESSORIES]
- framed mirror, pendant lighting
- premium towels

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "dining_room": """\
Apply modern luxury style to this dining room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- dining furniture style
- materials, colors
- decorative objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- marble, dark wood, velvet
- brass, glass

[COLORS]
- cream, black, gold
- deep green or navy

[FURNITURE]
- velvet or premium leather upholstered chairs
- elegant dining table

[DECOR]
- statement chandelier
- art pieces, fresh flowers

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "home_office": """\
Apply modern luxury style to this home office.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- desk and chair style
- shelving
- accessories

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- dark wood desk
- marble, leather, brass accents

[COLORS]
- cream, black, gold, walnut brown

[FURNITURE]
- executive desk in dark wood
- premium leather chair

[ACCESSORIES]
- brass desk lamp
- leather organizers, art
- refined executive feel

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "entryway": """\
Apply modern luxury style to this entryway.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- decorative objects

[WALLS]
- elegant matte cream or soft charcoal paint
- optional subtle panel molding
- remove any existing wallpaper

[MATERIALS]
- marble, dark wood
- brass, velvet

[COLORS]
- cream, black, gold accents

[FURNITURE]
- elegant console table
- statement mirror with gold frame

[DECOR]
- elegant vase, pendant light
- art piece

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",
}

# ═══════════════════════════════════════════
# 5. Warm Natural
# ═══════════════════════════════════════════

_WARM_GENERIC = """\
Apply warm natural interior style.

[KEEP EXACTLY]
- room layout, walls, windows, doors, ceiling
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style and placement
- materials, colors, textures
- decorative objects

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan, woven fibers
- cotton, linen, clay, ceramic

[COLORS]
- beige, warm brown, olive
- terracotta, cream, warm white

[TEXTURES]
- organic, textured, handcrafted feel
- layered naturals

[FURNITURE]
- rounded, comfortable, inviting forms
- warm wood and rattan

[DECOR]
- plants, woven baskets
- ceramic vases, soft throw blankets
- homey and nurturing

[DO NOT]
- change room layout or structure
- move or resize windows/doors
- change camera perspective
- redesign the space

Photorealistic interior photography."""

_WARM_ROOMS: dict[str, str] = {
    "kitchen": """\
Apply warm natural style to this kitchen.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- cabinet style and material
- countertop material
- hardware
- surface objects

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood cabinets, butcher block
- natural stone, ceramic

[COLORS]
- beige, warm brown, cream
- olive accents

[HARDWARE]
- rounded, brass or antique bronze

[DECOR]
- wooden cutting board, ceramic pot
- herbs, warm natural objects

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "living_room": """\
Apply warm natural style to this living room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- materials, colors, textures
- decorative objects

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan
- woven fibers, cotton, linen

[COLORS]
- beige, brown, olive
- terracotta, cream

[FURNITURE]
- rounded, comfortable, inviting
- warm wood frames, soft cushions

[DECOR]
- plants, woven baskets
- soft throw blankets, cushions

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bedroom": """\
Apply warm natural style to this bedroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- bed frame and bedding
- furniture style
- decorative objects

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan
- cotton, linen, wool

[COLORS]
- beige, warm brown, cream
- olive, terracotta accents

[BEDDING]
- layered linen and cotton
- earthy tones, textured throws

[DECOR]
- plants, woven basket
- ceramic lamp, natural rug

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "bathroom": """\
Apply warm natural style to this bathroom.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- vanity and storage style
- fixtures
- accessories

[WALLS]
- warm white or soft beige paint
- remove any existing wallpaper

[MATERIALS]
- warm wood, natural stone
- terracotta tile, ceramic

[COLORS]
- beige, warm brown, cream, olive

[FIXTURES]
- rounded, brass or antique bronze

[ACCESSORIES]
- woven basket, plant
- wooden tray, cotton towels

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "dining_room": """\
Apply warm natural style to this dining room.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- dining furniture style
- materials, colors
- decorative objects

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan
- woven fibers, linen, ceramic

[COLORS]
- beige, brown, olive
- terracotta, cream

[FURNITURE]
- wood or rattan chairs
- comfortable cushions

[DECOR]
- linen table runner, ceramic vase
- candles, plants

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "home_office": """\
Apply warm natural style to this home office.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- desk and chair style
- shelving
- accessories

[WALLS]
- warm white or soft beige paint
- optional natural texture finish
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan
- woven fibers, leather, linen

[COLORS]
- beige, brown, olive, cream

[FURNITURE]
- warm wood desk
- comfortable natural chair

[ACCESSORIES]
- ceramic pen holder, woven basket
- plant, warm desk lamp
- cozy and productive

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",

    "entryway": """\
Apply warm natural style to this entryway.

[KEEP EXACTLY]
- room layout, walls, windows, doors
- camera angle and perspective
- lighting direction and depth

[EDIT ONLY]
- wall surface finish
- furniture style
- decorative objects

[WALLS]
- warm white or soft beige paint
- remove any existing wallpaper

[MATERIALS]
- warm wood, rattan
- woven fibers, natural stone

[COLORS]
- beige, brown, cream, olive

[FURNITURE]
- warm wood bench or shelf
- round mirror with wood frame

[DECOR]
- woven basket, ceramic vase
- small plant, natural fiber rug

[DO NOT]
- change room layout or structure
- change camera perspective

Photorealistic interior photography.""",
}

# ═══════════════════════════════════════════
# Generic (fallback) prompts per style
# ═══════════════════════════════════════════

STAGING_TEMPLATES: dict[str, str] = {
    "japanese_muji": _MUJI_GENERIC,
    "scandinavian": _SCANDI_GENERIC,
    "modern_minimalist": _MODERN_GENERIC,
    "modern_luxury": _LUXURY_GENERIC,
    "warm_natural": _WARM_GENERIC,
}

# ── Room-specific prompt lookup ──

_STYLE_ROOM_PROMPTS: dict[str, dict[str, str]] = {
    "japanese_muji": _MUJI_ROOMS,
    "scandinavian": _SCANDI_ROOMS,
    "modern_minimalist": _MODERN_ROOMS,
    "modern_luxury": _LUXURY_ROOMS,
    "warm_natural": _WARM_ROOMS,
}


def get_staging_prompt(template: str, space_name: str) -> str | None:
    """Get the best staging prompt for a given style template and space name.

    Returns a room-specific prompt if the space name matches a known room type,
    otherwise falls back to the generic template prompt.
    Returns None if the template is unknown.
    """
    room_type = _classify_room(space_name)
    if room_type:
        room_prompts = _STYLE_ROOM_PROMPTS.get(template)
        if room_prompts and room_type in room_prompts:
            return room_prompts[room_type]

    return STAGING_TEMPLATES.get(template)
