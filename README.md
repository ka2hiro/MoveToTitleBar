# Move to TitleBar

キーボードショートカットでマウスポインタをアクティブウィンドウのタイトルバーへ瞬時に移動させる Windows 常駐アプリです。ウィンドウのドラッグ移動や閉じる操作をキーボード起点で行えるようになります。

## できること

- **Ctrl + Alt + T** — マウスポインタをアクティブウィンドウのタイトルバー中央に移動
- **Ctrl + Alt + X** — マウスポインタをアクティブウィンドウの閉じるボタン（×）に移動

タスクトレイに常駐し、トレイアイコンの右クリックメニューから一時的な無効化や終了ができます。

## 使い方

1. EXE をビルドする

   ```bash
   make
   ```

   `dist/move_to_titlebar.exe` が生成されます。

2. EXE を実行するとタスクトレイに青いアイコンが表示され、準備完了

3. 任意のウィンドウ上でショートカットキーを押すだけです

### Windows 起動時に自動で立ち上げる

1. `Win + R` で `shell:startup` と入力してスタートアップフォルダを開く
2. `dist/move_to_titlebar.exe` のショートカットをそのフォルダに作成

## ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照してください。

本プロジェクトは以下の LGPLv3 ライブラリに依存しています。ソースコードは各リポジトリから取得・改変が可能です。

- [pynput](https://github.com/moses-palmer/pynput) (LGPLv3)
- [pystray](https://github.com/moses-palmer/pystray) (LGPLv3)

その他の依存ライブラリを含む詳細は [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) を参照してください。
