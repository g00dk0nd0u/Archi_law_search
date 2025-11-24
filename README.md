# Archi Law Search（建築基準法・施行令検索）

建築基準法（`325AC0000000201`）と建築基準法施行令（`325CO0000000338`）を e-Gov 法令 API から取得し、ターミナル上で横断検索できる Textual 製 TUI アプリです。条番号・本文の両方でヒットを探し、本文表示・ハイライト・クリップボードコピーを行えます。

## 主な機能
- `src/ui_app.py` を用いた TUI で検索キーワード入力→結果リスト→本文表示まで完結
- 条番号一致と本文一致を分類して上限 100 件まで表示（法・令を横並びで確認可能）
- 全角数字や漢数字を正規化して条番号検索（`normalize_num`）し、枝番や「の◯」付きも検出
- 検索語を本文内でハイライト、本文や全件結果を JSON 形式でクリップボードへコピー
- e-Gov 法令 API v2 を日付指定（当日）で取得し、失敗時は安全にフォールバック

## セットアップ
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 起動方法
- TUI を起動: `python -m src.app` （または `python src/app.py`）
- 画面操作の流れ:
  - 画面上部の入力欄にキーワード（例: `111条`, `111条の2`, `耐火構造`）を入れて Enter
  - 結果リストで↑↓キー選択 → 本文が右側に表示・ハイライト
  - `Ctrl+C` で表示中の本文をコピー
  - 画面下部ボタン「All_results_Copy」で全件を JSON 配列としてコピー

※ 初回検索時に e-Gov へアクセスします（ネット接続が必要）。

## テスト・ユーティリティ
- 本文生成の欠損検査: `python -m tests.check_missing_content`  
  条番号を指定して限定スキャンする場合: `python -m tests.check_missing_content 111 120`

## EXE パッケージング
PyInstaller で Windows 実行ファイルを作る補助スクリプトを用意しています。
```powershell
# onedir 方式（デフォルト・起動高速）
python exe_packaging.py
# 1 ファイルにまとめる場合
python exe_packaging.py --onefile
```
ビルド物は `dist/` 配下に生成されます。PyInstaller が未導入なら自動でインストールします。

## ディレクトリと主要ファイル
- `src/app.py` … エントリーポイント兼 API/検索ロジックの再エクスポート
- `src/ui_app.py` … Textual ベースの UI 実装（検索・表示・コピー）
- `src/search_logic.py` … 条番号・本文検索、ハイライト語抽出、条文構造の整形
- `src/structure_extract.py` … e-Gov XML から段落・号構造を抽出しプレーンテキスト化
- `src/laws_api.py` … e-Gov 法令 API v2 へのフェッチと簡易フォールバック
- `tests/check_missing_content.py` … 本文生成の欠損チェック用スクリプト

## 開発メモ
- 文字化け対策やリンク生成ルールの検討メモは `memo.md` を参照してください。
