import os
import re
import time
import random
import subprocess
import traceback
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException


# ----------------------------
# 虎牙站点
# ----------------------------
LIVE_HOME = "https://www.huya.com/l"      # 全部直播页
CATEGORY_HOME = "https://www.huya.com/g"  # 分类总页

# 直播间链接：虎牙房间可能是纯数字，也可能是短域名（如 /qitux）
ROOM_RE = re.compile(r"^https?://(www\.)?huya\.com/([A-Za-z0-9_]+)(?:\?.*)?$")


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

    preferred_qualities: Tuple[str, ...] = (
        "蓝光20M", "蓝光10M", "蓝光8M", "蓝光6M",
        "蓝光4M", "蓝光2M", "蓝光", "超清", "流畅"
    )

    headless: bool = False

    # ✅ 复用 Chrome Profile（建议写成 --user-data-dir=...）
    user_data_arg: Optional[str] = None

    # ✅ 可选：指定 profile-directory（Default / Profile 1...）
    profile_directory: Optional[str] = None

    # ✅ 重启浏览器时的重试参数（profile 锁释放慢时很有用）
    driver_start_retries: int = 4
    driver_start_backoff: float = 1.2


# ----------------------------
# profile 锁处理（复用登录态 + 频繁重启必备）
# ----------------------------
def _profile_lock_files(user_data_dir: str) -> List[str]:
    names = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    return [os.path.join(user_data_dir, n) for n in names]


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

    # 减少缓存干扰
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
    """
    ✅ 复用同一个 user-data-dir 并频繁重启时：
    等待释放 + 重试 +（必要时）清锁（仅脚本专用 profile 时建议）
    """
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

                # 第二次及以后仍失败：尝试清锁（仅脚本专用 profile）
                if user_data_dir and i >= 1:
                    cleanup_profile_locks_if_needed(user_data_dir)
                continue

            raise

    raise last_err


def fast_wait(driver, timeout=2.0):
    return WebDriverWait(driver, timeout, poll_frequency=0.08)


# ----------------------------
# （可选）在虎牙播放器上“续命”：避免菜单自动消失
# ----------------------------
def start_huya_hover_keepalive(driver, interval_ms: int = 250):
    driver.execute_script(f"""
    try {{
      if (window.__huyaKeepAlive) clearInterval(window.__huyaKeepAlive);
      window.__huyaKeepAlive = setInterval(() => {{
        const menu = document.querySelector('.player-menu-panel.player-menu-panel-common');
        const btn  = document.querySelector('.player-videotype-cur')
                  || document.querySelector('.player-videotype-txt')
                  || document.querySelector('#player')
                  || document.querySelector('video');

        const el = (menu && menu.offsetParent) ? menu : btn;
        if (!el) return;

        const r = el.getBoundingClientRect();
        const x = Math.floor(r.left + Math.min(10, Math.max(1, r.width - 2)));
        const y = Math.floor(r.top  + Math.min(10, Math.max(1, r.height - 2)));

        ['mousemove','mouseover','mouseenter'].forEach(type => {{
          el.dispatchEvent(new MouseEvent(type, {{bubbles:true, clientX:x, clientY:y}}));
        }});
      }}, {interval_ms});
    }} catch(e) {{}}
    """)


def stop_huya_hover_keepalive(driver):
    driver.execute_script("""
    try {
      if (window.__huyaKeepAlive) clearInterval(window.__huyaKeepAlive);
      window.__huyaKeepAlive = null;
    } catch(e) {}
    """)


# ----------------------------
# 找 video（兼容 iframe）
# ----------------------------
def _find_visible_video_in_current_doc(driver):
    vids = driver.find_elements(By.CSS_SELECTOR, "video")
    for v in vids:
        try:
            if v.is_displayed():
                return v
        except Exception:
            pass
    return None


def _find_visible_video_anywhere(driver):
    driver.switch_to.default_content()
    v = _find_visible_video_in_current_doc(driver)
    if v:
        return v

    iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for f in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(f)
            v = _find_visible_video_in_current_doc(driver)
            if v:
                return v
        except Exception:
            continue

    driver.switch_to.default_content()
    return None


def scroll_until_video_appears(driver, timeout=20, step=900):
    end = time.time() + timeout
    while time.time() < end:
        v = _find_visible_video_anywhere(driver)
        if v:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});", v
            )
            return v

        driver.switch_to.default_content()
        driver.execute_script("window.scrollBy(0, arguments[0]);", step)
        time.sleep(0.35)

    raise TimeoutError("滚动后仍未找到 video（虎牙可能用更深层 iframe/自定义容器）")


# ----------------------------
# 虎牙：画质读取/打开菜单/点击画质/等待切换（支持模糊匹配 + 跳过扫码即享）
# ----------------------------
def _norm_quality_key(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = s.replace(" ", "").replace("\u3000", "")
    s = s.replace("m", "M")
    return s


def get_current_quality_huya(driver, timeout=3) -> str:
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".player-videotype-cur"))
        )
        return _norm_quality_key((el.text or "").strip())
    except Exception:
        pass

    try:
        el = driver.find_element(By.CSS_SELECTOR, ".player-videotype-list li.on span, .player-videotype-list li.on")
        return _norm_quality_key((el.text or "").strip())
    except Exception:
        return ""


def open_quality_menu_huya_fast(driver, timeout: float = 2.0) -> bool:
    wait = fast_wait(driver, timeout)

    try:
        player = driver.find_element(By.CSS_SELECTOR, "video, #player, .player-wrap, .player-box, .player-main")
        ActionChains(driver).move_to_element(player).perform()
    except Exception:
        pass

    try:
        panel = driver.find_element(By.CSS_SELECTOR, ".player-menu-panel.player-menu-panel-common")
        if panel.is_displayed():
            return True
    except Exception:
        pass

    for sel in [".player-videotype-cur", ".player-videotype-txt"]:
        try:
            el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            driver.execute_script("arguments[0].click();", el)
            break
        except Exception:
            continue

    try:
        wait.until(lambda d: d.execute_script("""
            const ul = document.querySelector('.player-videotype-list');
            if (!ul) return false;
            const panel = document.querySelector('.player-menu-panel.player-menu-panel-common');
            return !!((panel && panel.offsetParent) || (ul && ul.offsetParent));
        """))
        return True
    except Exception:
        return False


def click_quality_item_huya_fuzzy(driver, keyword: str) -> bool:
    kw = _norm_quality_key(keyword)
    js = r"""
    const kw = arguments[0];
    const ul = document.querySelector('.player-videotype-list');
    if (!ul) return false;

    const norm = (s) => (s || '').replace(/\s+/g,'').replace(/\u3000/g,'').replace(/m/g,'M');
    const items = Array.from(ul.querySelectorAll('li'));

    const candidates = items.filter(li => {
      if (!li) return false;
      const txt = li.innerText || '';
      if (txt.includes('扫码')) return false;
      if (li.querySelector('.common-enjoy-btn')) return false;
      return true;
    });

    if (!candidates.length) return false;

    let target = candidates.find(li => norm(li.innerText || '').includes(kw));
    if (!target && kw === '蓝光') {
      target = candidates.find(li => (li.innerText || '').includes('蓝光'));
    }
    if (!target) return false;

    const sp = target.querySelector('span') || target;
    sp.click();
    return true;
    """
    try:
        return bool(driver.execute_script(js, kw))
    except Exception:
        return False


def wait_quality_changed_huya_fast(driver, keyword: str, timeout: float = 2.5) -> bool:
    kw = _norm_quality_key(keyword)
    wait = fast_wait(driver, timeout)
    try:
        return wait.until(lambda d: kw in get_current_quality_huya(d))
    except Exception:
        try:
            return wait.until(lambda d: kw in _norm_quality_key(d.execute_script("""
                const on = document.querySelector('.player-videotype-list li.on');
                return on ? (on.innerText || '') : '';
            """) or ""))
        except Exception:
            return False


def select_quality_huya_fast(driver, preferred: Tuple[str, ...]):
    start_huya_hover_keepalive(driver, interval_ms=200)
    try:
        for q in preferred:
            for _ in range(2):
                if not open_quality_menu_huya_fast(driver, timeout=2.0):
                    continue
                if not click_quality_item_huya_fuzzy(driver, q):
                    continue
                if wait_quality_changed_huya_fast(driver, q, timeout=2.5):
                    return q
        return None
    finally:
        stop_huya_hover_keepalive(driver)


# ----------------------------
# 分类：从 https://www.huya.com/g 抓取 /g/xxx
# ----------------------------
def get_categories_huya(driver) -> Dict[str, str]:
    driver.get(CATEGORY_HOME)
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(1.5)

    cats: Dict[str, str] = {}
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    for a in anchors:
        href = (a.get_attribute("href") or "").strip()
        text = (a.text or "").strip()

        if not href or not text:
            continue

        if "huya.com/g/" in href:
            if len(text) <= 12 and href not in cats:
                cats[href] = text

    cats.setdefault(LIVE_HOME, "全部直播")
    return cats


# ----------------------------
# 分类页抓直播间链接
# ----------------------------
def scroll_to_load(driver, rounds: int = 6):
    for _ in range(rounds):
        driver.execute_script("window.scrollBy(0, document.documentElement.clientHeight * 0.9);")
        time.sleep(0.8)


def normalize_room_url(href: str) -> Optional[str]:
    if not href:
        return None
    href = href.strip()

    if "/g" in href or "/l" in href or "index.php" in href:
        return None

    if href.startswith("/"):
        href = "https://www.huya.com" + href

    href = href.split("?")[0]

    if ROOM_RE.match(href):
        return href
    return None


def get_live_rooms_in_category(driver, category_url: str, limit: int = 10) -> List[str]:
    driver.get(category_url)
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(1.5)

    rooms: Set[str] = set()

    for _ in range(10):
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            room = normalize_room_url(href)
            if room:
                rooms.add(room)
                if len(rooms) >= limit:
                    return list(rooms)[:limit]

        scroll_to_load(driver, rounds=1)

    return list(rooms)[:limit]


# ----------------------------
# tshark 抓包
# ----------------------------
def start_tshark_capture(cfg: RunConfig, filepath: str, duration: int) -> subprocess.Popen:
    tshark_cmd = [
        "tshark",
        "-q",
        "-a", f"duration:{duration}",
        "-w", filepath,
        "-i", cfg.network_iface,
    ]
    return subprocess.Popen(tshark_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------
# ✅ 单房间：抓包 +（每次新开浏览器）+ 打开 + 选画质 + 停留
#   要求：进入直播间前先关闭浏览器 -> 这里通过“每房间独立 driver”实现
#   且：必须复用登录态 -> 同一个 user-data-dir
# ----------------------------
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
        # 1) 先启动 tshark（全程抓包）
        tshark_proc = start_tshark_capture(cfg, tmp_filepath, duration)
        print(f"▶️ 开始抓包(临时): {tmp_filename}")

        # 2) ✅ 启动“全新浏览器实例”，复用同一登录态 profile
        driver = build_driver_with_retry(cfg)

        # 3) ✅ 输入直播间网址
        driver.get(room_url)
        time.sleep(5)

        # 可选：确保播放器露出来
        try:
            scroll_until_video_appears(driver, timeout=12)
        except Exception:
            pass

        print("加载完开始选择画质（虎牙）")
        picked = select_quality_huya_fast(driver, preferred=cfg.preferred_qualities)
        print(f"🎚️ 画质选择结果: {picked}")

        print(f"🖥️ 停留 {cfg.dwell_seconds}s: {room_url}")
        end_t = time.time() + cfg.dwell_seconds
        while time.time() < end_t:
            time.sleep(1.5)

    finally:
        # ✅ 先关浏览器，确保下一房间“进入前已关闭”
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        # ✅ 等 profile 锁释放（避免下一轮启动报“被占用”）
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

        # tshark 结束后改名
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


# ----------------------------
# 主流程
# ----------------------------
def main():
    cfg = RunConfig(
        chrome_binary=r".\chrome-win64\chrome.exe",
        chromedriver_path=r".\chromedriver-win64\chromedriver.exe",
        network_iface="WLAN",
        pcap_dir="captures",
        rooms_per_category=8,
        dwell_seconds=60,
        tshark_extra_seconds=5,
        preferred_qualities=("蓝光20M","蓝光10M","蓝光8M","蓝光6M","蓝光4M","蓝光2M","蓝光","超清","流畅"),
        headless=False,

        # ✅ 复用登录态（示例：你自己的路径）
        user_data_arg=r"--user-data-dir=C:\Users\****\AppData\Local\Google\Chrome for Testing\User Data",

        # ✅ 可选：指定 Default / Profile 1...
        profile_directory="Default",
    )

    # 用一个 driver 抓房间列表（抓完就关，释放 profile）
    list_driver = build_driver_with_retry(cfg)
    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    try:
        print("未能自动识别分类链接（页面结构可能更新）。请直接粘贴分类URL：")
        print("以下是常用分类URL，请选择或输入自定义URL：")
        print("- 颜值: https://www.huya.com/g/2168")
        print("- 星秀: https://www.huya.com/g/xingxiu")
        print("- 娱乐天地: https://www.huya.com/g/100022")
        print("- 交友: https://www.huya.com/g/4079")
        print("- 聊天: https://www.huya.com/g/5367")
        print("- 网游: https://www.huya.com/g/100023")
        print("- 手游: https://www.huya.com/g/100004")
        print("- 单机游戏: https://www.huya.com/g/100002")
        print("请直接粘贴分类URL：")

        category_url = "https://www.huya.com/g/100023"

        if "2168" in category_url:
            category_name = "娱乐1"
        elif "xingxiu" in category_url:
            category_name = "娱乐2"
        elif "100022" in category_url:
            category_name = "娱乐3"
        elif "4079" in category_url:
            category_name = "娱乐4"
        elif "5367" in category_url:
            category_name = "聊天"
        elif "100023" in category_url:
            category_name = "网游"
        elif "100004" in category_url:
            category_name = "手游"
        elif "100002" in category_url:
            category_name = "单机游戏"
        else:
            category_name = "manual"

        print(f"已设置分类: {category_name}")

        rooms = get_live_rooms_in_category(list_driver, category_url, limit=cfg.rooms_per_category)
        print(f"\n分类 [{category_name}] 抓到直播间数量: {len(rooms)}")
        for r in rooms:
            print(" -", r)

    finally:
        # ✅ 抓列表后立刻关掉 list_driver，释放 profile 给后续每房间重启用
        try:
            list_driver.quit()
        except Exception:
            pass
        if user_data_dir:
            wait_profile_released(user_data_dir, timeout=12.0)

    # ✅ 逐个房间：每次都“先没有浏览器（上一轮已关）→ 再启动浏览器 → 输入URL”
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


# 入口
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
        time.sleep(1)  # 可调：每次间隔 1 秒

