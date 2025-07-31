import sys
import pyautogui

def main():
    if len(sys.argv) != 3:
        print("Usage: click.py <x> <y>")
        sys.exit(1)

    x = int(sys.argv[1])
    y = int(sys.argv[2])
    pyautogui.click(x=x, y=y)

if __name__ == "__main__":
    main()