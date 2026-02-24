import os
import re   进口再保险
import time   导入的时间
import subprocess   导入子流程
import traceback
from datetime import datetime从datetime导入datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set
import pyautogui
import random
import threading

# Selenium 相关
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException


# 抖音直播首页
LIVE_HOME = "https://live.douyin.com/"
ROOM_RE = re.compile(r"^https?://live\.douyin\.com/\d+")

start_event = threading.Event()
stop_event = threading.Event()


# ----------------------------
# 运行配置
# ----------------------------
@dataclass
class RunConfig:
    chrome_binary: str = r"chrome-win64/chrome.exe"
    chromedriver_path: str = r"../chromedriver-win64/chromedriver-win64/chromedriver.exe"

    network_iface: str = "WLAN"
    pcap_dir: str = "../captures"

    rooms_per_category: int = 10
    dwell_seconds: int = 60
    tshark_extra_seconds: int = 5

    preferred_qualities: Tuple[str, ...] = ("原画", "高清", "标清", "自动")

    headless: bool = False

    # ✅ 必须复用登录态：建议写 --user-data-dir=...
    user_data_arg: Optional[str] = None

    # ✅ 可选：Default / Profile 1...
    profile_directory: Optional[str] = None

    # ✅ 重启浏览器时 profile 占用重试
    driver_start_retries: int = 4
    driver_start_backoff: float = 1.2


# ----------------------------
# profile 锁处理（复用登录态 + 频繁重启必备）
# ----------------------------
def _profile_lock_files(user_data_dir: str) -> List[str]:
    names = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    return [os.path.join(user_data_dir, n) for n in names]从datetime导入datetime


def get_user_data_dir_from_arg(user_data_arg: str) -> Optional[str]:
    if not user_data_arg:
        return None
    m = re.search(r"--user-data-dir=(.+)$", user_data_arg.strip())
    if not m:
        return None
    return m.group(1).strip().strip('"')


def wait_profile_released(user_data_dir: str, timeout: float = 12.0, poll: float = 0.25) -> bool:
    end = time.time() + timeout
    lock_files = _profile_lock_files(user_data_dir)
    while time.time() < end:
        if all(not os.path.exists(p) for p in lock_files):
            return True
        time.sleep(poll)
    return False


def cleanup_profile_locks_if_needed(user_data_dir: str) -> None:
    """
    ⚠️ 仅建议：这个 user-data-dir 是“专门给脚本用”的场景。
    确保你没有手动打开同一个 profile 的 Chrome。
    """
    for p in _profile_lock_files(user_data_dir):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


# ----------------------------
# Selenium：创建 driver
# ----------------------------
def build_driver(cfg: RunConfig) -> webdriver.Chrome:
    options = Options()
    options.binary_location = cfg.chrome_binary

    if cfg.headless:
        options.add_argument("--headless=new")

    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")

    options.add_argument("--disable-application-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--dns-prefetch-disable")

    if cfg.user_data_arg:
        arg = cfg.user_data_arg.strip()
        if not arg.startswith("--"):
            arg = "--" + arg
        options.add_argument(arg)

    if cfg.profile_directory:
        options.add_argument(f"--profile-directory={cfg.profile_directory}")

    service = Service(cfg.chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


def build_driver_with_retry(cfg: RunConfig) -> webdriver.Chrome:
    last_err = None
    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    for i in range(cfg.driver_start_retries):
        try:
            if user_data_dir:
                wait_profile_released(user_data_dir, timeout=8.0)
            return build_driver(cfg)

        except WebDriverException as e:
            last_err = e
            msg = str(e).lower()

            if ("user data directory is already in use" in msg) or ("profile" in msg and "in use" in msg):
                print(f"⚠️ profile 仍被占用，重试启动({i+1}/{cfg.driver_start_retries})...")
                time.sleep(cfg.driver_start_backoff * (i + 1))
                if user_data_dir and i >= 1:
                    cleanup_profile_locks_if_needed(user_data_dir)
                continue

            raise

    raise last_err


# --------------------------------
# Selenium：更稳的点击（失败则尝试 JS click）
# --------------------------------
def safe_click(driver, element) -> bool:
    try:
        time.sleep(0.1)
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def try_click_by_xpath(driver, xpath: str, timeout: int = 3) -> bool:
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
        return safe_click(driver, el)
    except Exception:
        return False


def move_mouse_fixed(x=1602, y=1200, duration=10):
    pyautogui.FAILSAFE = True
    pyautogui.moveTo(x, y, duration=duration)
    print(f"moved to ({x}, {y})")


# ----------------------------
# 质量菜单续命
# ----------------------------
def start_quality_hover_keepalive(driver, interval_ms: int = 300):
    driver.execute_script(f"""
    try {{
      if (window.__qKeepAlive) clearInterval(window.__qKeepAlive);
      window.__qKeepAlive = setInterval(() => {{
        const btn = document.querySelector('[data-e2e="quality"]');
        const panel = document.querySelector('[data-e2e="quality-selector"]');

        const el = (panel && panel.offsetParent) ? panel : btn;
        if (!el) return;

        const r = el.getBoundingClientRect();
        const x = Math.floor(r.left + Math.min(10, Math.max(1, r.width - 2)));
        const y = Math.floor(r.top  + Math.min(10, Math.max(1, r.height - 2)));

        ['mousemove','mouseover','mouseenter'].forEach(type => {{
          el.dispatchEvent(new MouseEvent(type, {{bubbles:true, clientX:x, clientY:y}}));
        }});
      }}, {interval_ms});
    }} catch (e) {{}}
    """)


def stop_quality_hover_keepalive(driver):
    driver.execute_script("""
    try {
      if (window.__qKeepAlive) clearInterval(window.__qKeepAlive);
      window.__qKeepAlive = null;
    } catch (e) {}
    """)


def open_quality_menu(driver, timeout: int = 6) -> bool:
    try:
        start_quality_hover_keepalive(driver)

        qbtn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="quality"]'))
        )
        driver.execute_script("arguments[0].click();", qbtn)

        WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="quality-selector"]'))
        )
        return True
    except Exception:
        return False


def _find_clickable_for_label(panel, label: str):
    xpath_exact = f".//*[normalize-space(text())='{label}']"
    nodes = panel.find_elements(By.XPATH, xpath_exact)

    if (not nodes) and label == "自动":
        xpath_auto = ".//*[starts-with(normalize-space(text()),'自动')]"
        nodes = panel.find_elements(By.XPATH, xpath_auto)

    if not nodes:
        return None

    text_node = nodes[0]

    candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::*[@onclick][1]")
    if candidates:
        return candidates[0]

    candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::*[@role='menuitem' or @role='button'][1]")
    if candidates:
        return candidates[0]

    candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::div[1]")
    if candidates:
        return candidates[0]

    return None


def select_quality(driver, preferred=("原画", "高清", "标清", "自动"), timeout: int = 6):
    try:
        start_quality_hover_keepalive(driver)

        if not open_quality_menu(driver, timeout=timeout):
            return None

        panel = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="quality-selector"]'))
        )

        for q in preferred:
            el = _find_clickable_for_label(panel, q)
            if el and el.is_displayed():
                driver.execute_script("arguments[0].click();", el)
                time.sleep(0.2)
                return q

        return None
    finally:
        stop_quality_hover_keepalive(driver)


# --------------------------------
# 获取分类
# --------------------------------
def get_categories_selenium(driver) -> Dict[str, str]:
    driver.get(LIVE_HOME)
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(2)

    cats: Dict[str, str] = {}
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    for a in anchors:
        href = (a.get_attribute("href") or "").strip()
        text = (a.text or "").strip()
        if not href or not text:
            continue
        if "live.douyin.com" in href and ("category" in href or "category_name" in href or "activity_name" in href):
            if href not in cats and len(text) <= 10:
                cats[href] = text
    return cats


def scroll_to_load(driver, rounds: int = 8):
    for _ in range(rounds):
        driver.execute_script("window.scrollBy(0, document.documentElement.clientHeight * 0.9);")
        time.sleep(0.8)


def get_live_rooms_in_category(driver, category_url: str, limit: int = 10) -> List[str]:
    driver.get(category_url)
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(2)

    rooms: Set[str] = set()
    for _ in range(10):
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            if ROOM_RE.match(href):
                rooms.add(href.split("?")[0])
                if len(rooms) >= limit:
                    return list(rooms)[:limit]
        scroll_to_load(driver, rounds=1)

    return list(rooms)[:limit]


# --------------------------------
# tshark 抓包
# --------------------------------
def start_tshark_capture(cfg: RunConfig, filepath: str, duration: int) -> subprocess.Popen:
    tshark_cmd = [
        "tshark",
        "-q",
        "-a", f"duration:{duration}",
        "-w", filepath,
        "-i", cfg.network_iface,
    ]
    return subprocess.Popen(tshark_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------
# ✅ 单房间采集：内部自己启动/关闭浏览器（实现“进房前先关浏览器再输网址”）
# --------------------------------
def run_capture_session_restart_browser(cfg: RunConfig, category_name: str, room_url: str):
    os.makedirs(cfg.pcap_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_cat = re.sub(r"[\\/:*?\"<>|]", "_", category_name or "unknown")

    tmp_filename = f"{safe_cat}_pending_{timestamp}.pcap"
    tmp_filepath = os.path.join(cfg.pcap_dir, tmp_filename)

    duration = cfg.dwell_seconds + cfg.tshark_extra_seconds

    tshark_proc = None
    driver = None
    picked = None

    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    try:
        # 1) 先 tshark
        tshark_proc = start_tshark_capture(cfg, tmp_filepath, duration)
        print(f"▶️ 开始抓包(临时): {tmp_filename}")

        # 2) ✅ 启动新浏览器（复用登录态）
        driver = build_driver_with_retry(cfg)

        # 3) ✅ 输入直播间网址
        driver.get(room_url)
        time.sleep(5)

        print("加载完开始选择画质")
        picked = select_quality(driver, preferred=cfg.preferred_qualities)
        print(f"🎚️ 画质选择结果: {picked}")

        print(f"🖥️ 停留 {cfg.dwell_seconds}s: {room_url}")
        end_t = time.time() + cfg.dwell_seconds
        while time.time() < end_t:
            time.sleep(1.5)

    finally:
        # ✅ 先关浏览器（保证下一个房间进入前已关闭）
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        # ✅ 等 profile 锁释放
        if user_data_dir:
            if not wait_profile_released(user_data_dir, timeout=12.0):
                print("⚠️ profile 锁未及时释放，下一轮将重试/必要时清锁")

        # 再结束 tshark
        if tshark_proc:
            try:
                tshark_proc.wait(timeout=15)
            except Exception:
                tshark_proc.terminate()
                try:
                    tshark_proc.wait(timeout=5)
                except Exception:
                    pass

        # 改名
        safe_picked = re.sub(r"[\\/:*?\"<>|]", "_", (picked or "unknown")).replace(" ", "")
        final_filename = f"{safe_cat}_{safe_picked}_{timestamp}.pcap"
        final_filepath = os.path.join(cfg.pcap_dir, final_filename)

        try:
            if os.path.exists(final_filepath):
                suffix = random.randint(1000, 9999)
                final_filename = f"{safe_cat}_{safe_picked}_{timestamp}_{suffix}.pcap"
                final_filepath = os.path.join(cfg.pcap_dir, final_filename)

            os.rename(tmp_filepath, final_filepath)
            print(f"🛑 抓包已保存: {final_filepath}\n")
        except Exception as e:
            print(f"⚠️ 改名失败，保留临时文件: {tmp_filepath}，原因: {e}\n")


# --------------------------------
# 主流程：先抓 rooms（用 list_driver），再逐房间重启浏览器采集
# --------------------------------
def main():
    cfg = RunConfig(
        chrome_binary=r"D:\Undergraduate_study\Project\LiveTafficCapture\chrome-win64\chrome.exe",
        chromedriver_path=r"D:\Undergraduate_study\Project\LiveTafficCapture\chromedriver-win64\chromedriver-win64\chromedriver.exe",
        network_iface="WLAN",
        pcap_dir="captures",
        rooms_per_category=8,
        dwell_seconds=60,
        tshark_extra_seconds=5,
        preferred_qualities=("原画", "高清", "标清", "自动"),
        headless=False,

        # ✅ 必须复用登录态：注意要带 --
        user_data_arg=r"--user-data-dir=C:\Users\WangH\AppData\Local\Google\Chrome for Testing\User Data",
        # 可选：profile_directory="Default",
    )

    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    # 1) 用 list_driver 抓分类/房间列表（抓完就关）
    list_driver = build_driver_with_retry(cfg)
    try:
        categories = get_categories_selenium(list_driver)

        if categories:
            print("检测到分类（可能不全）：")
            items = list(categories.items())
            for i, (u, name) in enumerate(items, 1):
                print(f"{i}. {name}  |  {u}")

            print("\n输入序号选择分类；或直接粘贴分类URL：")
            choice = input().strip()

            if choice.isdigit() and 1 <= int(choice) <= len(items):
                category_url, category_name = items[int(choice) - 1]
            else:
                category_url = choice
                category_name = "manual"
        else:
            print("未能自动识别分类链接（页面结构可能更新）。请直接粘贴分类URL：")
            category_url = input().strip()
            category_name = "manual"

        rooms = get_live_rooms_in_category(list_driver, category_url, limit=cfg.rooms_per_category)
        print(f"\n分类 [{category_name}] 抓到直播间数量: {len(rooms)}")
        for r in rooms:
            print(" -", r)

    finally:
        try:
            list_driver.quit()
        except Exception:
            pass
        if user_data_dir:
            wait_profile_released(user_data_dir, timeout=12.0)

    if not rooms:
        print("没有抓到房间，退出。")
        return

    # 2) ✅ 逐房间采集：每次都重启浏览器
    for idx, room_url in enumerate(rooms, 1):
        try:
            print(f"\n===== [{idx}/{len(rooms)}] 开始采集: {room_url} =====")
            run_capture_session_restart_browser(cfg, category_name, room_url)
        except Exception as e:
            print(f"❌ 直播间采集失败，跳过: {room_url}")
            print(f"   异常类型: {type(e).__name__}")
            print(f"   异常信息: {e}")
            traceback.print_exc()
            time.sleep(2)
            continue


# 入口：无限循环
if __name__ == "__main__":
    i = 0
    while True:
        i += 1
        try:
            print(f"第 {i} 次运行开始")
            main()
            print(f"第 {i} 次运行结束")
        except Exception as e:
            print(f"第 {i} 次运行报错：{e}")
            traceback.print_exc()
        time.sleep(1)

