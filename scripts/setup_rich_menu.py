"""建立 LINE Rich Menu（重新開始 / 使用說明）。

Usage:
    python scripts/setup_rich_menu.py

需要環境變數:
    LINE_CHANNEL_ACCESS_TOKEN — LINE Messaging API channel access token
"""

from __future__ import annotations

import os
import sys

import httpx

TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
BASE = "https://api.line.me/v2/bot"

if not TOKEN:
    print("❌ 請設定 LINE_CHANNEL_ACCESS_TOKEN 環境變數")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


def create_rich_menu() -> str:
    """建立 Rich Menu，回傳 richMenuId。"""
    # 2500x843 是 LINE 建議的尺寸（compact 用 2500x422）
    body = {
        "size": {"width": 2500, "height": 422},
        "selected": True,  # 預設展開
        "name": "ReelEstate 主選單",
        "chatBarText": "選單",
        "areas": [
            {
                # 左半邊：重新開始
                "bounds": {"x": 0, "y": 0, "width": 1250, "height": 422},
                "action": {"type": "message", "label": "重新開始", "text": "重新開始"},
            },
            {
                # 右半邊：使用說明
                "bounds": {"x": 1250, "y": 0, "width": 1250, "height": 422},
                "action": {"type": "message", "label": "使用說明", "text": "使用說明"},
            },
        ],
    }
    resp = httpx.post(f"{BASE}/richmenu", json=body, headers=headers)
    resp.raise_for_status()
    rich_menu_id = resp.json()["richMenuId"]
    print(f"✓ Rich Menu 建立成功: {rich_menu_id}")
    return rich_menu_id


def upload_image(rich_menu_id: str, image_path: str) -> None:
    """上傳 Rich Menu 背景圖片。"""
    with open(image_path, "rb") as f:
        resp = httpx.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            content=f.read(),
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "image/png",
            },
        )
    resp.raise_for_status()
    print(f"✓ 圖片上傳成功")


def set_default(rich_menu_id: str) -> None:
    """設為所有使用者的預設 Rich Menu。"""
    resp = httpx.post(
        f"{BASE}/user/all/richmenu/{rich_menu_id}",
        headers=headers,
    )
    resp.raise_for_status()
    print(f"✓ 已設為預設 Rich Menu")


def delete_old_menus() -> None:
    """刪除所有舊的 Rich Menu。"""
    resp = httpx.get(f"{BASE}/richmenu/list", headers=headers)
    resp.raise_for_status()
    menus = resp.json().get("richmenus", [])
    for menu in menus:
        rid = menu["richMenuId"]
        httpx.delete(f"{BASE}/richmenu/{rid}", headers=headers)
        print(f"  刪除舊選單: {rid}")
    if menus:
        print(f"✓ 已刪除 {len(menus)} 個舊選單")


def main() -> None:
    print("=== ReelEstate Rich Menu 設定 ===\n")

    # 1. 刪除舊選單
    print("1. 清除舊選單...")
    delete_old_menus()

    # 2. 建立新選單
    print("\n2. 建立新選單...")
    rich_menu_id = create_rich_menu()

    # 3. 上傳圖片
    image_path = os.path.join(os.path.dirname(__file__), "rich_menu.png")
    if os.path.exists(image_path):
        print("\n3. 上傳選單圖片...")
        upload_image(rich_menu_id, image_path)
    else:
        print(f"\n3. ⚠️  找不到 {image_path}")
        print("   請準備 2500x422 的 PNG 圖片，左右各一個按鈕：")
        print("   左：「🔄 重新開始」  右：「📖 使用說明」")
        print(f"   放到 {image_path} 後重新執行，或手動上傳：")
        print(f"   curl -X POST https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content \\")
        print(f'     -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \\')
        print(f'     -H "Content-Type: image/png" \\')
        print(f"     --data-binary @rich_menu.png")
        print("\n   上傳圖片後，手動設為預設：")
        print(f"   curl -X POST {BASE}/user/all/richmenu/{rich_menu_id} \\")
        print(f'     -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN"')
        return

    # 4. 設為預設
    print("\n4. 設為預設選單...")
    set_default(rich_menu_id)

    print("\n=== 完成！所有使用者都會看到 Rich Menu ===")


if __name__ == "__main__":
    main()
