#!/usr/bin/env python3
"""
songs.json を対話形式で編集するCLIツール。

想定実行環境: Raspberry Pi OS (Linux) / Python 3
依存: jsonschema (pip install jsonschema --break-system-packages)
     git コマンドがPATH上にあること（git add/commit/push に使用）

操作: 追加 / 編集 / 削除 / 終了(保存) / 保存後にgit add・commit・push
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import jsonschema
except ImportError:
    print("エラー: jsonschema がインストールされていません。")
    print("次のコマンドでインストールしてください:")
    print("  pip install jsonschema --break-system-packages")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent.parent
SONGS_PATH = BASE_DIR / "songs.json"
SCHEMA_PATH = BASE_DIR / "schema" / "songs.schema.json"

JST = timezone(timedelta(hours=9))

DEFAULT_ENGINE = "分析採点AI"
ID_PATTERN = re.compile(r"^song-(\d+)$")

# 詳細項目: (JSONキー, 表示ラベル)
DETAIL_FIELDS = [
    ("pitch", "音程"),
    ("stability", "安定感"),
    ("expression", "抑揚"),
    ("long_tone", "ロングトーン"),
    ("technique", "テクニック"),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_schema() -> dict:
    return load_json(SCHEMA_PATH)


def validate(data: dict, schema: dict) -> list:
    """バリデーションを行い、エラーメッセージのリストを返す（空リストなら正常）。"""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    messages = [f"  - {'/'.join(map(str, e.path))}: {e.message}" for e in errors]

    # Schema単体では表現しづらい追加チェック（エンジン重複のみ）
    for song in data.get("songs", []):
        engines_seen = set()
        for rec in song.get("karaoke", []):
            engine = rec.get("engine")
            if engine in engines_seen:
                messages.append(
                    f"  - songs[{song.get('id')}]: エンジン '{engine}' が重複しています"
                )
            engines_seen.add(engine)
    return messages


def next_id(data: dict) -> str:
    max_num = 0
    for song in data.get("songs", []):
        m = ID_PATTERN.match(song["id"])
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"song-{max_num + 1:03d}"


def prompt(label: str, default: str = None, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if not value and allow_empty:
            return ""
        if value:
            return value
        print("  → 空欄にはできません。入力してください。")


def prompt_score(label: str) -> float:
    while True:
        raw = input(f"{label} (0-100の数値): ").strip()
        try:
            value = float(raw)
        except ValueError:
            print("  → 数値を入力してください。")
            continue
        if not (0 <= value <= 100):
            print("  → 0〜100の範囲で入力してください。")
            continue
        return value


def prompt_optional_score(label: str) -> Optional[float]:
    """空Enterならスキップ(None)を許す点数入力。"""
    while True:
        raw = input(f"    {label} (0-100の数値 / 不明なら空Enter): ").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            print("      → 数値を入力してください。")
            continue
        if not (0 <= value <= 100):
            print("      → 0〜100の範囲で入力してください。")
            continue
        return value


def input_score_details(existing: dict = None) -> dict:
    """
    音程・安定感・抑揚・ロングトーン・テクニックを対話形式で入力する。
    空Enterでスキップした項目は null として記録する（既存値は引き継がない）。
    常に5項目すべてをキーとして返す。
    """
    existing = existing or {}
    print("  --- 詳細項目（分からない項目は空Enterでスキップ→nullで記録） ---")
    details = {}
    for key, label in DETAIL_FIELDS:
        prior = existing.get(key)
        prior_note = f" (前回値: {prior})" if prior is not None else ""
        value = prompt_optional_score(f"{label}{prior_note}")
        details[key] = value  # None ならそのまま null として記録
    return details


def prompt_yes_no(label: str, default_no: bool = True) -> bool:
    suffix = "(y/N)" if default_no else "(Y/n)"
    raw = input(f"{label} {suffix}: ").strip().lower()
    if not raw:
        return not default_no
    return raw in ("y", "yes")


def input_karaoke_records(existing: list = None) -> list:
    """
    採点記録を対話形式で入力する。
    existing が渡された場合は編集モードとして、既存記録をベースに確認しながら進める。
    """
    records = []
    existing = existing or []
    existing_by_engine = {r["engine"]: r for r in existing}
    used_engines = set()

    print("\n--- 採点記録の入力 ---")
    print(f"(1件目: Enterのみ→「{DEFAULT_ENGINE}」を使用 / '-' 入力→未採点として終了)")

    while True:
        is_first = not records
        label = "採点エンジン名"
        raw = input(f"{label} [{DEFAULT_ENGINE if is_first else ''}]: ").strip()

        if is_first and raw == "-":
            # 採点記録なしで終了
            return []
        if not raw and is_first:
            engine = DEFAULT_ENGINE
        elif not raw and not is_first:
            print("  → エンジン名を入力してください（入力終了は次の確認で選べます）。")
            continue
        else:
            engine = raw

        if engine in used_engines:
            print(f"  → '{engine}' は既に入力済みです。別のエンジン名にしてください。")
            continue
        used_engines.add(engine)

        prior = existing_by_engine.get(engine)
        prior_highest = prior["highest"] if prior else None
        if prior_highest:
            print(f"  (既存の最高点: {prior_highest['score']})")

        score = prompt_score("  最高点（総合点）")

        highest = {"score": score}
        if prompt_yes_no("  この回の詳細項目（音程・安定感・抑揚・ロングトーン・テクニック）を入力しますか？"):
            details = input_score_details(
                existing=prior_highest.get("details") if prior_highest else None
            )
            if details:
                highest["details"] = details

        records.append({"engine": engine, "highest": highest})

        if not prompt_yes_no("他にも採点記録がありますか？"):
            break
        first_default = None  # 2件目以降はデフォルト提案しない

    return records


def add_song(data: dict) -> None:
    print("\n=== 新規曲の追加 ===")
    song_id = next_id(data)
    print(f"ID: {song_id} (自動採番)")
    title = prompt("曲名")
    artist = prompt("アーティスト名")
    reason = prompt("好きな理由", allow_empty=True)
    karaoke = input_karaoke_records()

    song = {
        "id": song_id,
        "title": title,
        "artist": artist,
        "reason": reason,
        "karaoke": karaoke,
    }
    data["songs"].append(song)
    print(f"→ {song_id} 「{title}」を追加しました（まだ保存されていません。終了時に保存されます）")


def list_songs(data: dict) -> None:
    songs = data.get("songs", [])
    if not songs:
        print("(登録曲はまだありません)")
        return
    for i, song in enumerate(songs, start=1):
        engines = ", ".join(r["engine"] for r in song["karaoke"]) or "未採点"
        print(f"{i}. [{song['id']}] {song['title']} / {song['artist']} ({engines})")


def select_song(data: dict):
    songs = data.get("songs", [])
    if not songs:
        print("(登録曲はまだありません)")
        return None
    list_songs(data)
    raw = input("番号を選択してください（キャンセルは空Enter）: ").strip()
    if not raw:
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= len(songs)):
        print("  → 無効な番号です。")
        return None
    return songs[int(raw) - 1]


def edit_song(data: dict) -> None:
    print("\n=== 曲の編集 ===")
    song = select_song(data)
    if song is None:
        return

    print(f"\n編集中: {song['id']} 「{song['title']}」")
    print("(各項目は空Enterで現在値のまま変更しません)")
    song["title"] = prompt("曲名", default=song["title"])
    song["artist"] = prompt("アーティスト名", default=song["artist"])
    song["reason"] = prompt("好きな理由", default=song["reason"], allow_empty=True)

    if prompt_yes_no("採点記録を編集しますか？（未回答なら現状維持）"):
        song["karaoke"] = input_karaoke_records(existing=song["karaoke"])

    print(f"→ {song['id']} を更新しました（まだ保存されていません。終了時に保存されます）")


def delete_song(data: dict) -> None:
    print("\n=== 曲の削除 ===")
    song = select_song(data)
    if song is None:
        return
    if prompt_yes_no(f"本当に「{song['title']}」({song['id']}) を削除しますか？"):
        data["songs"].remove(song)
        print(f"→ {song['id']} を削除しました（まだ保存されていません。終了時に保存されます）")
    else:
        print("キャンセルしました。")


def run_git(args: list, cwd: Path) -> "subprocess.CompletedProcess":
    """gitコマンドを実行し、結果を返す。呼び出し元でreturncodeを確認すること。"""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def git_has_changes(cwd: Path, rel_path: str) -> bool:
    """指定パスに未コミットの変更（未追跡含む）があるか確認する。"""
    result = run_git(["status", "--porcelain", "--", rel_path], cwd=cwd)
    if result.returncode != 0:
        print("  → git status の実行に失敗しました:")
        print(f"    {result.stderr.strip()}")
        return False
    return bool(result.stdout.strip())


def git_add_commit_push(cwd: Path, rel_path: str) -> None:
    """
    songs.json の変更を git add / commit / push する。
    各ステップで失敗した場合はエラー内容を表示し、以降の処理を中止する。
    """
    if not git_has_changes(cwd, rel_path):
        print("  → git上での変更が検出されませんでした（addは不要です）。")
        return

    add_result = run_git(["add", rel_path], cwd=cwd)
    if add_result.returncode != 0:
        print("  → git add に失敗しました:")
        print(f"    {add_result.stderr.strip()}")
        return
    print(f"  → git add {rel_path} 完了")

    default_message = f"Update {rel_path} ({datetime.now(JST).strftime('%Y-%m-%d %H:%M')})"
    message = prompt("  コミットメッセージ", default=default_message)

    commit_result = run_git(["commit", "-m", message], cwd=cwd)
    if commit_result.returncode != 0:
        print("  → git commit に失敗しました:")
        print(f"    {commit_result.stderr.strip() or commit_result.stdout.strip()}")
        return
    print("  → git commit 完了")

    if not prompt_yes_no("  リモートにpushしますか？"):
        print("  → push はスキップしました（commitは完了しています）。")
        return

    push_result = run_git(["push"], cwd=cwd)
    if push_result.returncode != 0:
        print("  → git push に失敗しました:")
        print(f"    {push_result.stderr.strip()}")
        print("  → commitはローカルに残っています。認証やネットワークを確認し、")
        print("    後で手動で `git push` するか、次回保存時に再度お試しください。")
        return
    print("  → git push 完了")


def main():
    if not SONGS_PATH.exists():
        print(f"エラー: {SONGS_PATH} が見つかりません。")
        sys.exit(1)

    data = load_json(SONGS_PATH)
    schema = load_schema()

    print("=== 好きな曲・カラオケ記録 編集ツール ===")
    print(f"対象ファイル: {SONGS_PATH}")

    while True:
        print("\n--- メニュー ---")
        print("1. 曲を追加")
        print("2. 曲を編集")
        print("3. 曲を削除")
        print("4. 一覧表示")
        print("5. 保存して終了")
        print("6. 保存せず終了")
        choice = input("選択してください: ").strip()

        if choice == "1":
            add_song(data)
        elif choice == "2":
            edit_song(data)
        elif choice == "3":
            delete_song(data)
        elif choice == "4":
            print()
            list_songs(data)
        elif choice == "5":
            data["updated_at"] = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
            errors = validate(data, schema)
            if errors:
                print("\n保存前チェックでエラーが見つかりました。保存を中止します:")
                print("\n".join(errors))
                print("メニューに戻ります。内容を修正してから再度保存してください。")
                continue
            save_json(SONGS_PATH, data)
            print(f"\n{SONGS_PATH} に保存しました。")

            if prompt_yes_no("この内容を git commit してpushしますか？"):
                git_add_commit_push(BASE_DIR, SONGS_PATH.relative_to(BASE_DIR).as_posix())

            break
        elif choice == "6":
            if prompt_yes_no("変更を破棄して終了しますか？"):
                print("保存せずに終了しました。")
                break
        else:
            print("→ 1〜6の番号を入力してください。")


if __name__ == "__main__":
    main()
