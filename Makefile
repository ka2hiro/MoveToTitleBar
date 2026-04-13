PYTHON = python
PIP = pip
STAMP = .installed

.PHONY: all build run clean

all: $(STAMP) build

$(STAMP):
	$(PIP) install pywin32 pynput pystray pillow pyinstaller customtkinter
	touch $(STAMP)

build: $(STAMP)
	pyinstaller --onefile --noconsole --collect-data customtkinter --version-file=version_info.txt move_to_titlebar.py

run: $(STAMP)
	$(PYTHON) move_to_titlebar.py

clean:
	rm -rf build dist *.spec $(STAMP)
