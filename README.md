# Live Channel Access Automation (Selenium + WebDriver-Manager)

We use automated scripts (Selenium with WebDriver-Manager) to simulate user access to web-based live channels across multiple content categories.

Supported live-streaming platforms:
- Bilibili (哔哩哔哩)
- Douyin (抖音)
- Douyu (斗鱼)
- Huya (虎牙)

---

## Prerequisites

- Windows (example paths below use Windows-style paths)
- Python 3.9+ (recommended)
- Chrome / Chrome for Testing available on your machine
- tshark/Wireshark installed (if packet capture is enabled) and permission to write to `pcap_dir`

> Note: Some platforms require login for stable playback and/or quality selection. Reusing an existing Chrome login profile is strongly recommended.

---
## Configuration

Before running, you **must** update the following fields in `RunConfig` to match your local machine:

- `chrome_binary`
- `chromedriver_path`
- `network_iface`
- `user_data_arg`

### Example

```python
cfg = RunConfig(
    chrome_binary=r".\chrome-win64\chrome.exe",
    chromedriver_path=r".\chromedriver-win64\chromedriver-win64\chromedriver.exe",
    network_iface="WLAN",
    pcap_dir="captures",
    rooms_per_category=8,
    dwell_seconds=60,
    tshark_extra_seconds=5,
    preferred_qualities=("原画", "高清", "标清", "自动"),
    headless=False,

    # ✅ Login state must be reused: keep the leading `--`
    user_data_arg=r"--user-data-dir=C:\Users\*****\AppData\Local\Google\Chrome for Testing\User Data",

    # Optional: if your login state is in "Profile 1", set it to "Profile 1".
    # The default is typically "Default".
    profile_directory="Default",
)
