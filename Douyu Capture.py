# -*- coding: utf-8 -*-
"""
Douyu Live Crawler + Autoplay Click + Quality Selector + tshark Capture
----------------------------------------------------------------------
改造点（按你要求）：
- ✅ 每次进入直播间前：先关闭浏览器（上一房间已 quit） -> 再启动新浏览器 -> 输入直播间网址
- ✅ 必须复用登录态：同一个 --user-data-dir
"""

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
from selenium.common.exceptions import TimeoutException, WebDriverException


# ----------------------------
# 站点常量（斗鱼）
# ----------------------------
LIVE_HOME = "https://www.douyu.com/"
ROOM_RE = re.compile(r"^https?://www\.douyu\.com/\d+/?$")


# ----------------------------
# 运行配置
# ----------------------------
@dataclass
class RunConfig:
    chrome_binary: str = r"chrome-win64/chrome.exe"
    chromedriver_path: str = r"../chromedriver-win64/chromedriver-win64/chromedriver.exe"

    network_iface: str = "WLAN"
    pcap_dir: str = "../captures_douyu"

    rooms_per_category: int = 10
    dwell_seconds: int = 60
    tshark_extra_seconds: int = 5

    preferred_qualities: Tuple[str, ...] = ("原画", "蓝光", "超清", "高清")

    headless: bool = False

    # ✅ 必须复用登录态：建议写成 --user-data-dir=...
    user_data_arg: Optional[str] = None

    # ✅ 可选：指定 profile-directory（Default / Profile 1...）
    profile_directory: Optional[str] = None

    # ✅ profile 占用重试参数
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
# 房间 URL 规范化
# ----------------------------
def normalize_room_url(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return f"https://www.douyu.com/{s}"
    if s.startswith("http"):
        s = s.split("?")[0].rstrip("/")
        if ROOM_RE.match(s) or ROOM_RE.match(s + "/"):
            return s
    return None


# ----------------------------
# ✅ Autoplay 遮罩 “真实鼠标点击”
# ----------------------------
def _move_mouse_to_player(driver):
    try:
        el = driver.find_element(By.CSS_SELECTOR, "video")
        ActionChains(driver).move_to_element(el).perform()
        return
    except Exception:
        pass
    try:
        el = driver.find_element(By.CSS_SELECTOR, "#room-html5-player, #__h5player, #douyu_room_normal_player_proxy_box")
        ActionChains(driver).move_to_element(el).perform()
        return
    except Exception:
        pass


def _mouse_click_element(driver, el) -> bool:
    try:
        if not el.is_displayed():
            return False
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
        except Exception:
            pass
        ActionChains(driver).move_to_element(el).pause(0.05).click(el).perform()
        return True
    except Exception:
        return False


def douyu_mouse_click_autoplay_if_present(driver) -> bool:
    _move_mouse_to_player(driver)

    # 1) 点图标：class 含 autoPlayImg
    try:
        icons = driver.find_elements(By.CSS_SELECTOR, '[class*="autoPlayImg"]')
        for ic in icons:
            if _mouse_click_element(driver, ic):
                return True
    except Exception:
        pass

    # 2) 点遮罩：class 含 autoplay
    try:
        overlays = driver.find_elements(By.CSS_SELECTOR, '[class*="autoplay"]')
        for ov in overlays:
            if _mouse_click_element(driver, ov):
                return True
    except Exception:
        pass

    return False


def douyu_autoplay_guard(driver, seconds: float = 8.0, interval: float = 0.25) -> int:
    end = time.time() + seconds
    cnt = 0
    while time.time() < end:
        if douyu_mouse_click_autoplay_if_present(driver):
            cnt += 1
            time.sleep(0.35)
        else:
            time.sleep(interval)
    return cnt


# ----------------------------
# 画质选择（尽量泛化）
# ----------------------------
def start_douyu_hover_keepalive(driver, interval_ms: int = 220):
    driver.execute_script(
        f"""
        try {{
          if (window.__douyuKeepAlive) clearInterval(window.__douyuKeepAlive);
          window.__douyuKeepAlive = setInterval(() => {{
            const player = document.querySelector('#room-html5-player')
                        || document.querySelector('#__h5player')
                        || document.querySelector('video');

            const rate = Array.from(document.querySelectorAll('[class*="rate-"]'))
                        .find(el => el.querySelector('[class*="textLabel"]')) || null;

            const el = rate || player;
            if (!el) return;

            const r = el.getBoundingClientRect();
            const x = Math.floor(r.left + Math.min(10, Math.max(2, r.width - 2)));
            const y = Math.floor(r.top  + Math.min(10, Math.max(2, r.height - 2)));

            ['mousemove','mouseover','mouseenter'].forEach(type => {{
              el.dispatchEvent(new MouseEvent(type, {{bubbles:true, clientX:x, clientY:y}}));
            }});
          }}, {interval_ms});
        }} catch(e) {{}}
        """
    )


def stop_douyu_hover_keepalive(driver):
    driver.execute_script(
        """
        try {
          if (window.__douyuKeepAlive) clearInterval(window.__douyuKeepAlive);
          window.__douyuKeepAlive = null;
        } catch(e) {}
        """
    )


def douyu_get_current_quality_text(driver, timeout=3) -> str:
    el = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="rate-"] [class*="textLabel"]'))
    )
    return (el.text or "").strip()


def douyu_open_quality_panel(driver, timeout=3) -> bool:
    _move_mouse_to_player(driver)

    try:
        rate = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="rate-"]'))
        )
        ActionChains(driver).move_to_element(rate).perform()
    except Exception:
        return False

    try:
        def panel_visible(d):
            return d.execute_script(r"""
                function isVisible(el){
                  if(!el) return false;
                  const st = window.getComputedStyle(el);
                  if(!st) return false;
                  if(st.display === 'none' || st.visibility === 'hidden') return false;
                  return (el.offsetParent !== null);
                }
                const rate = Array.from(document.querySelectorAll('[class*="rate-"]'))
                          .find(el => el.querySelector('[class*="textLabel"]')) || null;
                if(!rate) return false;
                const tips = Array.from(rate.querySelectorAll('[class*="tip"]'));
                for(const t of tips){
                  const inputs = Array.from(t.querySelectorAll('input'));
                  const ok = inputs.some(i => (i.value||'').trim().startsWith('画质'));
                  if(ok && isVisible(t)) return true;
                }
                return false;
            """)
        WebDriverWait(driver, timeout).until(panel_visible)
        return True
    except Exception:
        return False


def douyu_click_quality(driver, keyword: str) -> bool:
    js_find = r"""
    const kw = arguments[0];
    function isVisible(el){
      if(!el) return false;
      const st = window.getComputedStyle(el);
      if(!st) return false;
      if(st.display === 'none' || st.visibility === 'hidden') return false;
      return (el.offsetParent !== null);
    }
    const rate = Array.from(document.querySelectorAll('[class*="rate-"]'))
              .find(el => el.querySelector('[class*="textLabel"]')) || null;
    if(!rate) return null;

    const tips = Array.from(rate.querySelectorAll('[class*="tip"]'));
    let visibleTip = null;
    for(const t of tips){
      const inputs = Array.from(t.querySelectorAll('input'));
      const ok = inputs.some(i => (i.value||'').trim().startsWith('画质'));
      if(ok && isVisible(t)){ visibleTip = t; break; }
    }
    if(!visibleTip) return null;

    const items = Array.from(visibleTip.querySelectorAll('[class*="tipItem"]'));
    let qItem = null;
    for(const it of items){
      const inp = it.querySelector('input');
      if(inp && (inp.value||'').trim().startsWith('画质')){ qItem = it; break; }
    }
    if(!qItem) return null;

    const lis = Array.from(qItem.querySelectorAll('ul li')).filter(li => {
      const txt = (li.innerText||'').trim();
      if(!txt) return false;
      if(txt.includes('画质增强')) return false;
      return true;
    });

    const target = lis.find(li => (li.innerText||'').includes(kw));
    return target || null;
    """
    try:
        el = driver.execute_script(js_find, keyword)
        if not el:
            return False
        return _mouse_click_element(driver, el)
    except Exception:
        return False


def douyu_wait_quality_changed(driver, keyword: str, timeout=3) -> bool:
    try:
        WebDriverWait(driver, timeout, poll_frequency=0.1).until(
            lambda d: keyword in douyu_get_current_quality_text(d, timeout=2)
        )
        return True
    except Exception:
        return False


def select_quality_douyu_fast(driver, preferred=("原画", "蓝光", "超清", "高清")) -> Optional[str]:
    start_douyu_hover_keepalive(driver, interval_ms=220)
    try:
        for q in preferred:
            for _ in range(2):
                douyu_mouse_click_autoplay_if_present(driver)

                if not douyu_open_quality_panel(driver, timeout=3):
                    continue
                if not douyu_click_quality(driver, q):
                    continue
                if douyu_wait_quality_changed(driver, q, timeout=3):
                    try:
                        return douyu_get_current_quality_text(driver, timeout=2)
                    except Exception:
                        return q
        return None
    finally:
        stop_douyu_hover_keepalive(driver)


# ----------------------------
# 分类页抓房间（简易）
# ----------------------------
def scroll_to_load(driver, rounds: int = 8):
    for _ in range(rounds):
        driver.execute_script("window.scrollBy(0, document.documentElement.clientHeight * 0.9);")
        time.sleep(0.8)


def get_live_rooms_in_category_douyu(driver, category_url: str, limit: int = 10) -> List[str]:
    driver.get(category_url)
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(2)

    rooms: Set[str] = set()

    for _ in range(14):
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            href = href.split("?")[0].rstrip("/")
            if ROOM_RE.match(href) or ROOM_RE.match(href + "/"):
                rooms.add(href)
                if len(rooms) >= limit:
                    return list(rooms)[:limit]
        scroll_to_load(driver, rounds=1)

    return list(rooms)[:limit]


# ----------------------------
# （可选）从斗鱼首页粗略抓分类（抓不到也没关系）
# ----------------------------
def get_categories_douyu_simple(driver) -> Dict[str, str]:
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
        # 常见分区是 /g_xxx
        if "douyu.com/g_" in href and len(text) <= 10:
            href = href.split("?")[0]
            if href not in cats:
                cats[href] = text
    return cats


# ----------------------------
# ✅ 单直播间：每次“新开浏览器输入网址”，并复用登录态
# ----------------------------
def run_capture_session_douyu_restart_browser(cfg: RunConfig, category_name: str, room_url: str):
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
        # 1) 先启动 tshark
        tshark_proc = start_tshark_capture(cfg, tmp_filepath, duration)
        print(f"▶️ 开始抓包(临时): {tmp_filename}")

        # 2) ✅ 启动新浏览器（复用登录态 profile）
        driver = build_driver_with_retry(cfg)

        # 3) ✅ 输入直播间网址
        driver.get(room_url)
        time.sleep(1.0)

        # 4) autoplay 遮罩：看见就点
        c = douyu_autoplay_guard(driver, seconds=8.0, interval=0.25)
        if c:
            print(f"▶️ autoplay遮罩鼠标点击次数: {c}")

        # 5) 选画质
        print("加载完开始选择画质(斗鱼)")
        picked = select_quality_douyu_fast(driver, preferred=cfg.preferred_qualities)
        print(f"🎚️ 画质选择结果: {picked}")

        # 6) 停留：全程持续检查遮罩
        print(f"🖥️ 停留 {cfg.dwell_seconds}s: {room_url}")
        end_t = time.time() + cfg.dwell_seconds
        while time.time() < end_t:
            douyu_mouse_click_autoplay_if_present(driver)
            time.sleep(0.6)

    finally:
        # ✅ 先关浏览器（满足“进入下一房间前先关闭浏览器”）
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

        # ✅ 等 profile 锁释放（避免下一轮启动被占用）
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
# 主流程（先抓 rooms，再逐个房间重启浏览器采集）
# ----------------------------
def main():
    cfg = RunConfig(
        chrome_binary=r".\chrome-win64\chrome.exe",
        chromedriver_path=r".\chromedriver-win64\chromedriver-win64\chromedriver.exe",
        network_iface="WLAN",
        pcap_dir="captures",
        rooms_per_category=8,
        dwell_seconds=60,
        tshark_extra_seconds=5,
        preferred_qualities=("原画", "蓝光", "超清", "高清"),
        headless=False,

        # ✅ 必须复用登录态（注意要带 --）
        user_data_arg=r"--user-data-dir=C:\Users\***\AppData\Local\Google\Chrome for Testing\User Data",

        # 可选：如果你的登录态在 Default / Profile 1
        profile_directory="Default",
    )

    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    # 1) 用 list_driver 抓分类/房间列表（抓完就关）
    list_driver = build_driver_with_retry(cfg)
    try:
        # categories = get_categories_douyu_simple(list_driver)
        #
        # if categories:
        #     print("检测到分类（可能不全）：")
        #     items = list(categories.items())
        #     for i, (u, name) in enumerate(items, 1):
        #         print(f"{i}. {name}  |  {u}")
        #
        #     print("\n输入序号选择分类；或直接粘贴分类URL：")
        #     choice = input().strip()
        #
        #     if choice.isdigit() and 1 <= int(choice) <= len(items):
        #         category_url, category_name = items[int(choice) - 1]
        #     else:
        #         category_url = choice
        #         category_name = "manual"
        # else:
        print("未能自动识别分类链接（正常现象，斗鱼结构常变）。请直接粘贴分类URL：")
        print("- 热门游戏: https://www.douyu.com/g_rmyx")
        print("- 户外: https://www.douyu.com/g_HW")
        print("- 星秀: https://www.douyu.com/g_xingxiu")
        print("- 二次元: https://www.douyu.com/g_ecy")
        print("- 聊天: https://www.douyu.com/g_xdpd")
        print("- 派对: https://www.douyu.com/g_paidui")
        print("- 单机游戏: https://www.douyu.com/g_OG")
        print("请直接粘贴分类URL：")

        category_url = input().strip()

        if "g_xdpd" in category_url:
            category_name = "聊天"
        elif "g_paidui" in category_url:
            category_name = "派对"
        elif "g_xingxiu" in category_url:
            category_name = "星秀"
        elif "g_rmyx" in category_url:
            category_name = "热门游戏"
        elif "g_OG" in category_url:
            category_name = "单机游戏"
        else:
            category_name = "manual"

        print(f"已设置分类: {category_name}")

        rooms = get_live_rooms_in_category_douyu(list_driver, category_url, limit=cfg.rooms_per_category)
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

    # 2) ✅ 逐个房间：每次都“先关闭浏览器（上一轮已 quit）→ 再启动新浏览器 → 输入 room_url”
    for idx, room_url in enumerate(rooms, 1):
        try:
            print(f"\n===== [{idx}/{len(rooms)}] 开始采集: {room_url} =====")
            run_capture_session_douyu_restart_browser(cfg, category_name, room_url)
        except Exception as e:
            print(f"❌ 直播间采集失败，跳过: {room_url}")
            print(f"   异常类型: {type(e).__name__}")
            print(f"   异常信息: {e}")
            traceback.print_exc()
            time.sleep(2)
            continue


# 入口：无限循环运行（你原来的行为）
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

