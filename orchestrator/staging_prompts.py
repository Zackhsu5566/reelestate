"""Room-specific staging prompts for virtual staging.

Each style has a generic (fallback) prompt and room-specific prompts
that give more precise material/color/texture guidance per room type.
"""

from __future__ import annotations

# ── Room name mapping ──
# Maps Chinese space names to canonical room type keys.
# 主臥/次臥/臥室 all map to "bedroom", etc.

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


# ── Shared prefix/suffix for all room-specific prompts ──

_ROOM_PREFIX = (
    "Edit the image to apply a {style_label} style.\n"
    "Preserve the original image exactly:\n"
    "- same architecture, walls, windows, doors, and spatial structure\n"
    "- same camera angle and perspective\n"
    "- same lighting direction and depth\n"
    "Do NOT change the room structure or camera viewpoint.\n"
    "Furniture can be replaced or restyled to match the {style_label} aesthetic.\n"
)

_ROOM_SUFFIX = (
    "The result must look like the same photo taken from the same angle "
    "with updated style, not a newly generated or redesigned scene.\n"
    "If architecture or camera angle changes, the result is incorrect.\n"
    "Highly realistic interior photography"
)


def _room_prompt(style_label: str, room_section: str) -> str:
    return _ROOM_PREFIX.format(style_label=style_label) + room_section + _ROOM_SUFFIX


# ═══════════════════════════════════════════
# 1. Japanese Muji / Japandi
# ═══════════════════════════════════════════

_MUJI = "Japanese Muji / Japandi"

_MUJI_ROOMS: dict[str, str] = {
    "kitchen": _room_prompt(_MUJI, (
        "Kitchen update:\n"
        "- materials → light wood, oak, ash\n"
        "- colors → white, beige, light brown\n"
        "- textures → clean, minimal, natural\n"
        "- hardware → simple, matte black or brushed nickel\n"
    )),
    "living_room": _room_prompt(_MUJI, (
        "Living room update:\n"
        "- materials → light wood, oak, ash, natural linen\n"
        "- colors → white, beige, warm grey, light brown\n"
        "- textures → clean, minimal, natural fabrics, matte finishes\n"
        "- furniture style → low-profile, simple lines\n"
        "- decor → minimal, zen-inspired\n"
    )),
    "bedroom": _room_prompt(_MUJI, (
        "Bedroom update:\n"
        "- materials → light wood, oak, ash, natural cotton, linen\n"
        "- colors → white, beige, soft grey, light brown\n"
        "- textures → clean, minimal, natural fibers, matte surfaces\n"
        "- bedding → simple, neutral tones, no patterns\n"
    )),
    "bathroom": _room_prompt(_MUJI, (
        "Bathroom update:\n"
        "- materials → light wood, oak, ash, natural stone, matte ceramic\n"
        "- colors → white, beige, warm grey, light brown\n"
        "- textures → clean, minimal, natural, matte finishes\n"
        "- fixtures → simple, rounded, matte black or brushed nickel\n"
    )),
    "dining_room": _room_prompt(_MUJI, (
        "Dining room update:\n"
        "- materials → light wood, oak, ash, natural linen\n"
        "- colors → white, beige, warm grey, light brown\n"
        "- textures → clean, minimal, natural grain, matte finishes\n"
        "- furniture → simple form, wood or wood-and-fabric\n"
    )),
    "home_office": _room_prompt(_MUJI, (
        "Home office update:\n"
        "- materials → light wood, oak, ash, natural paper, linen\n"
        "- colors → white, beige, warm grey, light brown\n"
        "- textures → clean, minimal, natural, matte finishes\n"
        "- accessories → minimal, functional, uncluttered\n"
    )),
    "entryway": _room_prompt(_MUJI, (
        "Entryway update:\n"
        "- materials → light wood, oak, ash, natural stone\n"
        "- colors → white, beige, warm grey, light brown\n"
        "- textures → clean, minimal, natural, matte finishes\n"
        "- decor → minimal, functional\n"
    )),
}

# ═══════════════════════════════════════════
# 2. Scandinavian
# ═══════════════════════════════════════════

_SCANDI = "Scandinavian"

_SCANDI_ROOMS: dict[str, str] = {
    "kitchen": _room_prompt(_SCANDI, (
        "Kitchen update:\n"
        "- materials → light wood, birch, pine, matte laminate\n"
        "- colors → white, light grey, soft wood tones\n"
        "- textures → clean, functional, natural grain\n"
        "- hardware → simple handles, matte black or brushed steel\n"
        "- add cozy touches → small indoor plant, textile dish towel\n"
    )),
    "living_room": _room_prompt(_SCANDI, (
        "Living room update:\n"
        "- materials → light wood, birch, pine, wool, cotton\n"
        "- colors → white, light grey, soft blue, warm wood\n"
        "- textures → cozy textiles, soft rug, knit throw blanket\n"
        "- furniture style → simple modern, rounded edges\n"
        "- add warmth → indoor plants, candles, soft lighting\n"
    )),
    "bedroom": _room_prompt(_SCANDI, (
        "Bedroom update:\n"
        "- materials → light wood, birch, pine, cotton, wool\n"
        "- colors → white, light grey, soft pastels, warm wood\n"
        "- textures → cozy bedding, knit throw, soft rug\n"
        "- bedding → layered whites and greys, textured fabrics\n"
        "- add warmth → small plant, warm bedside lamp\n"
    )),
    "bathroom": _room_prompt(_SCANDI, (
        "Bathroom update:\n"
        "- materials → light wood, birch, white ceramic, natural stone\n"
        "- colors → white, light grey, warm wood accents\n"
        "- textures → clean, matte, natural grain\n"
        "- fixtures → simple, functional, chrome or matte black\n"
        "- add warmth → woven basket, small plant, cotton towels\n"
    )),
    "dining_room": _room_prompt(_SCANDI, (
        "Dining room update:\n"
        "- materials → light wood, birch, pine, natural linen\n"
        "- colors → white, light grey, warm wood tones\n"
        "- textures → natural grain, soft fabric seats, matte finishes\n"
        "- furniture → simple wood or wood-and-fabric chairs\n"
        "- add warmth → candles, linen table runner, indoor plant\n"
    )),
    "home_office": _room_prompt(_SCANDI, (
        "Home office update:\n"
        "- materials → light wood, birch, pine, wool, cotton\n"
        "- colors → white, light grey, warm wood accents\n"
        "- textures → natural grain, soft textiles, matte\n"
        "- accessories → functional organizers, small plant, warm desk lamp\n"
        "- keep clutter-free but lived-in feel\n"
    )),
    "entryway": _room_prompt(_SCANDI, (
        "Entryway update:\n"
        "- materials → light wood, birch, pine, natural fiber\n"
        "- colors → white, light grey, warm wood\n"
        "- textures → natural grain, woven, matte\n"
        "- decor → woven basket, small mirror, hooks in matte black\n"
        "- add warmth → small plant, textile runner\n"
    )),
}

# ═══════════════════════════════════════════
# 3. Modern Minimalist
# ═══════════════════════════════════════════

_MODERN = "modern minimalist"

_MODERN_ROOMS: dict[str, str] = {
    "kitchen": _room_prompt(_MODERN, (
        "Kitchen update:\n"
        "- materials → matte lacquer, engineered stone, stainless steel\n"
        "- colors → white, grey, black accents\n"
        "- textures → sleek, smooth, polished surfaces\n"
        "- hardware → handleless or slim bar handles, matte black\n"
        "- keep surfaces completely clean and uncluttered\n"
    )),
    "living_room": _room_prompt(_MODERN, (
        "Living room update:\n"
        "- materials → glass, metal, polished concrete, leather\n"
        "- colors → white, grey, black, monochrome\n"
        "- textures → sleek, smooth, matte-and-gloss contrast\n"
        "- furniture style → clean geometric lines, low-profile\n"
        "- reduce decoration to absolute minimum\n"
    )),
    "bedroom": _room_prompt(_MODERN, (
        "Bedroom update:\n"
        "- materials → lacquer, metal, engineered surfaces, crisp cotton\n"
        "- colors → white, grey, charcoal, black accents\n"
        "- textures → smooth, matte, crisp\n"
        "- bedding → solid color, no patterns, clean edges\n"
        "- keep nightstands bare with minimal objects\n"
    )),
    "bathroom": _room_prompt(_MODERN, (
        "Bathroom update:\n"
        "- materials → engineered stone, glass, metal, large-format tile\n"
        "- colors → white, grey, black accents\n"
        "- textures → polished, smooth, seamless\n"
        "- fixtures → geometric, wall-mounted, matte black or chrome\n"
        "- frameless glass, clean lines, no visible clutter\n"
    )),
    "dining_room": _room_prompt(_MODERN, (
        "Dining room update:\n"
        "- materials → glass, metal, lacquer, engineered stone\n"
        "- colors → white, grey, black, monochrome\n"
        "- textures → sleek, polished, smooth\n"
        "- furniture → clean geometric form, no ornamentation\n"
        "- minimal tableware, no centerpiece clutter\n"
    )),
    "home_office": _room_prompt(_MODERN, (
        "Home office update:\n"
        "- materials → glass, metal, lacquer, engineered surfaces\n"
        "- colors → white, grey, black\n"
        "- textures → sleek, smooth, matte\n"
        "- accessories → absolute minimum, hidden storage\n"
        "- cable management invisible, clean desktop\n"
    )),
    "entryway": _room_prompt(_MODERN, (
        "Entryway update:\n"
        "- materials → metal, glass, lacquer, engineered stone\n"
        "- colors → white, grey, black\n"
        "- textures → sleek, smooth, polished\n"
        "- decor → single statement piece only, hidden storage\n"
        "- keep completely uncluttered\n"
    )),
}

# ═══════════════════════════════════════════
# 4. Modern Luxury
# ═══════════════════════════════════════════

_LUXURY = "modern luxury"

_LUXURY_ROOMS: dict[str, str] = {
    "kitchen": _room_prompt(_LUXURY, (
        "Kitchen update:\n"
        "- materials → marble countertop, dark wood cabinets, brushed gold hardware\n"
        "- colors → white, black, gold accents, cream\n"
        "- textures → polished stone, rich wood grain, metallic sheen\n"
        "- hardware → brushed gold or brass handles\n"
        "- add subtle luxury → under-cabinet lighting, statement backsplash\n"
    )),
    "living_room": _room_prompt(_LUXURY, (
        "Living room update:\n"
        "- materials → marble, velvet, premium leather, dark wood, brass\n"
        "- colors → cream, black, gold, deep green or navy accents\n"
        "- textures → polished, layered, rich fabrics, glossy-and-matte\n"
        "- furniture style → elegant silhouettes, refined upholstery\n"
        "- add luxury → statement lighting, art pieces, layered cushions\n"
    )),
    "bedroom": _room_prompt(_LUXURY, (
        "Bedroom update:\n"
        "- materials → velvet, silk, dark wood, marble, brass accents\n"
        "- colors → cream, gold, charcoal, deep jewel tone accents\n"
        "- textures → rich, layered, soft, polished\n"
        "- bedding → plush, layered textures, tufted headboard feel\n"
        "- add luxury → statement bedside lamps, art above bed, curtain drapes\n"
    )),
    "bathroom": _room_prompt(_LUXURY, (
        "Bathroom update:\n"
        "- materials → marble, natural stone, brass, dark wood accents\n"
        "- colors → white, cream, gold, black accents\n"
        "- textures → polished stone, metallic sheen, rich grain\n"
        "- fixtures → brushed gold or brass, elegant forms\n"
        "- add luxury → framed mirror, pendant lighting, premium towels\n"
    )),
    "dining_room": _room_prompt(_LUXURY, (
        "Dining room update:\n"
        "- materials → marble, dark wood, velvet, brass, glass\n"
        "- colors → cream, black, gold, deep green or navy\n"
        "- textures → polished, layered, rich, glossy accents\n"
        "- furniture → velvet or premium leather upholstered chairs\n"
        "- add luxury → statement chandelier, art pieces, fresh flowers\n"
    )),
    "home_office": _room_prompt(_LUXURY, (
        "Home office update:\n"
        "- materials → dark wood, marble, leather, brass accents\n"
        "- colors → cream, black, gold, walnut brown\n"
        "- textures → polished, rich grain, leather, metallic\n"
        "- accessories → brass desk lamp, leather organizers, art\n"
        "- refined and executive feel\n"
    )),
    "entryway": _room_prompt(_LUXURY, (
        "Entryway update:\n"
        "- materials → marble, dark wood, brass, velvet\n"
        "- colors → cream, black, gold accents\n"
        "- textures → polished stone, rich wood, metallic sheen\n"
        "- decor → statement mirror with gold frame, elegant vase\n"
        "- add luxury → pendant light, art piece\n"
    )),
}

# ═══════════════════════════════════════════
# 5. Warm Natural
# ═══════════════════════════════════════════

_WARM = "warm natural"

_WARM_ROOMS: dict[str, str] = {
    "kitchen": _room_prompt(_WARM, (
        "Kitchen update:\n"
        "- materials → warm wood, butcher block, natural stone, ceramic\n"
        "- colors → beige, warm brown, cream, olive accents\n"
        "- textures → organic grain, handcrafted tile, matte\n"
        "- hardware → rounded, brass or antique bronze\n"
        "- add warmth → wooden cutting board, ceramic pot, herbs\n"
    )),
    "living_room": _room_prompt(_WARM, (
        "Living room update:\n"
        "- materials → warm wood, rattan, woven fibers, cotton, linen\n"
        "- colors → beige, brown, olive, terracotta, cream\n"
        "- textures → organic, layered textiles, handcrafted feel\n"
        "- furniture style → rounded, comfortable, inviting\n"
        "- add warmth → plants, woven baskets, soft throw blankets, cushions\n"
    )),
    "bedroom": _room_prompt(_WARM, (
        "Bedroom update:\n"
        "- materials → warm wood, rattan, cotton, linen, wool\n"
        "- colors → beige, warm brown, cream, olive, terracotta accents\n"
        "- textures → organic, layered, soft, handcrafted\n"
        "- bedding → layered linen and cotton, earthy tones, textured throws\n"
        "- add warmth → plants, woven basket, ceramic lamp, natural rug\n"
    )),
    "bathroom": _room_prompt(_WARM, (
        "Bathroom update:\n"
        "- materials → warm wood, natural stone, terracotta tile, ceramic\n"
        "- colors → beige, warm brown, cream, olive\n"
        "- textures → organic, matte, handcrafted tile, natural grain\n"
        "- fixtures → rounded, brass or antique bronze\n"
        "- add warmth → woven basket, plant, wooden tray, cotton towels\n"
    )),
    "dining_room": _room_prompt(_WARM, (
        "Dining room update:\n"
        "- materials → warm wood, rattan, woven fibers, linen, ceramic\n"
        "- colors → beige, brown, olive, terracotta, cream\n"
        "- textures → organic grain, handcrafted, layered naturals\n"
        "- furniture → wood or rattan chairs, comfortable cushions\n"
        "- add warmth → linen table runner, ceramic vase, candles, plants\n"
    )),
    "home_office": _room_prompt(_WARM, (
        "Home office update:\n"
        "- materials → warm wood, rattan, woven fibers, leather, linen\n"
        "- colors → beige, brown, olive, cream\n"
        "- textures → organic, natural grain, handcrafted\n"
        "- accessories → ceramic pen holder, woven basket, plant, warm desk lamp\n"
        "- cozy and productive atmosphere\n"
    )),
    "entryway": _room_prompt(_WARM, (
        "Entryway update:\n"
        "- materials → warm wood, rattan, woven fibers, natural stone\n"
        "- colors → beige, brown, cream, olive\n"
        "- textures → organic, natural grain, handcrafted\n"
        "- decor → woven basket, ceramic vase, round mirror with wood frame\n"
        "- add warmth → small plant, natural fiber rug\n"
    )),
}

# ═══════════════════════════════════════════
# Generic (fallback) prompts per style
# ═══════════════════════════════════════════

STAGING_TEMPLATES: dict[str, str] = {
    "japanese_muji": (
        "Transform the interior into a Japanese Muji / Japandi style. "
        "Preserve the original architecture exactly: walls, windows, doors, ceiling, and spatial structure must remain unchanged. "
        "Keep the same camera angle and perspective. "
        "Furniture can be replaced or restyled to match the design language. "
        "Update materials, colors, textures, and decorations consistently across the entire space. "
        "Use realistic materials, proper lighting, and coherent spatial design. "
        "Interior design photography, natural lighting, clean composition, high realism."
    ),
    "scandinavian": (
        "Transform the interior into a Scandinavian style. "
        "Preserve the original architecture exactly: walls, windows, doors, ceiling, and spatial structure must remain unchanged. "
        "Keep the same camera angle and perspective. "
        "Furniture can be replaced or restyled to match the design language. "
        "Update materials, colors, textures, and decorations consistently across the entire space. "
        "Use realistic materials, proper lighting, and coherent spatial design. "
        "Interior design photography, natural lighting, clean composition, high realism."
    ),
    "modern_minimalist": (
        "Transform the interior into a modern minimalist style. "
        "Preserve the original architecture exactly: walls, windows, doors, ceiling, and spatial structure must remain unchanged. "
        "Keep the same camera angle and perspective. "
        "Furniture can be replaced or restyled to match the design language. "
        "Update materials, colors, textures, and decorations consistently across the entire space. "
        "Use realistic materials, proper lighting, and coherent spatial design. "
        "Interior design photography, natural lighting, clean composition, high realism."
    ),
    "modern_luxury": (
        "Transform the interior into a modern luxury style. "
        "Preserve the original architecture exactly: walls, windows, doors, ceiling, and spatial structure must remain unchanged. "
        "Keep the same camera angle and perspective. "
        "Furniture can be replaced or restyled to match the design language. "
        "Update materials, colors, textures, and decorations consistently across the entire space. "
        "Use realistic materials, proper lighting, and coherent spatial design. "
        "Interior design photography, natural lighting, clean composition, high realism."
    ),
    "warm_natural": (
        "Transform the interior into a warm natural style. "
        "Preserve the original architecture exactly: walls, windows, doors, ceiling, and spatial structure must remain unchanged. "
        "Keep the same camera angle and perspective. "
        "Furniture can be replaced or restyled to match the design language. "
        "Update materials, colors, textures, and decorations consistently across the entire space. "
        "Use realistic materials, proper lighting, and coherent spatial design. "
        "Interior design photography, natural lighting, clean composition, high realism."
    ),
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
