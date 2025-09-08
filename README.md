# kjvsimple
KJVSimple is a Python3 bible reader with minimalist curses interface.

To use this vibe code inspired software you only need the complete `KJV.txt` along side the script or specified by a path.
It supports book/chapter selection, jump to verse, searching with regex, copy verse to clipboard, and a basic bookmark/favorites functionality with user defined highlighting.
Bookmarks are saved to `".kjvsimple_favorites.json`. Some sample bookmarks are included.

### Dependencies

* Python3
* pyperclip (optional, to use copy to clipboard functionality)
* windows-curses (if on Windows)
