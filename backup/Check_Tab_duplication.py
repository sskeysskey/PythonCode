import subprocess
from collections import defaultdict
import sys

def get_chrome_tabs():
    # AppleScript to get the URL, window index and tab index of all tabs in Chrome
    script = '''
    tell application "Google Chrome"
        set windowList to every window
        set tabInfoList to {}

        repeat with i from 1 to count of windowList
            set aWindow to item i of windowList
            set tabList to every tab of aWindow
            repeat with j from 1 to count of tabList
                set aTab to item j of tabList
                set tabURL to URL of aTab
                set end of tabInfoList to {i, j, tabURL}
            end repeat
        end repeat

        set output to ""
        repeat with tabInfo in tabInfoList
            set output to output & (item 1 of tabInfo) & "," & (item 2 of tabInfo) & "," & (item 3 of tabInfo) & "\n"
        end repeat

        return output
    end tell
    '''
    
    # Run the AppleScript
    proc = subprocess.Popen(['osascript', '-e', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    
    if stderr:
        raise Exception(f"Error getting Chrome tabs: {stderr.decode('utf-8')}")
    
    # Decode the result
    tab_info_list = stdout.decode('utf-8').strip().split("\n")
    return [tuple(tab_info.split(",")) for tab_info in tab_info_list]

def find_duplicate_tabs(tab_infos):
    # Create a dictionary to store URLs and their corresponding positions
    url_positions = defaultdict(list)
    
    for window_index, tab_index, tab_url in tab_infos:
        url_positions[tab_url].append((window_index, tab_index))
    
    return {url: positions for url, positions in url_positions.items() if len(positions) > 1}

def main():
    try:
        tab_infos = get_chrome_tabs()
        duplicate_tabs = find_duplicate_tabs(tab_infos)
        
        if duplicate_tabs:
            print("Duplicate URLs found:")
            for url, positions in duplicate_tabs.items():
                print(f"URL: {url}")
                print(f"Number of duplicates: {len(positions)}")
                for window_index, tab_index in positions:
                    print(f" - Window: {window_index}, Tab: {tab_index}")
        else:
            print("No duplicate URLs found.")
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()