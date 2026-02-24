#
# import os
# import re
# import time
# import subprocess
# import traceback
# from datetime import datetime
# from dataclasses import dataclass
# from typing import Dict, List, Tuple, Optional, Set
# import pyautogui
# import random
# import threading
# # Selenium 相关
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.common.action_chains import ActionChains
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
#
#
#
# # 抖音直播首页
# LIVE_HOME = "https://live.douyin.com/"
#
# # 用于匹配直播间链接：live.douyin.com/数字
# ROOM_RE = re.compile(r"^https?://live\.douyin\.com/\d+")
# start_event = threading.Event()
# stop_event = threading.Event()
#
# # ----------------------------
# # 运行配置：把所有可调参数集中到一个地方
# # ----------------------------
# @dataclass
# class RunConfig:
#     # Chrome 浏览器程序路径（你的 portable chrome 或系统 chrome 均可）
#     chrome_binary: str = r"chrome-win64/chrome.exe"
#
#     # chromedriver 路径
#     chromedriver_path: str = r"../chromedriver-win64/chromedriver-win64/chromedriver.exe"
#
#     # tshark 抓包网卡名称（以 tshark -D 显示为准）
#     network_iface: str = "WLAN"
#
#     # pcap 输出目录
#     pcap_dir: str = "../captures"
#
#     # 每个分类页最多采集多少个直播间
#     rooms_per_category: int = 10
#
#     # 每个直播间停留时间（秒）
#     dwell_seconds: int = 60
#
#     # tshark 抓包时长会比停留时长多一点点，避免丢尾巴
#     tshark_extra_seconds: int = 5
#
#     # 画质选择优先级（会按顺序尝试点击：原画→高清→标清→自动）
#     preferred_qualities: Tuple[str, ...] = ("原画", "高清", "标清", "自动")
#
#     # 是否无头模式（直播播放器控件可能会不显示，不建议开启）
#     headless: bool = False
#
#     # 如果你需要复用已登录的 Chrome Profile，可把参数写在这里
#     # 示例：--user-data-dir=C:\Users\xxx\AppData\Local\Google\Chrome\User Data
#     # 或者同时加 profile-directory（但这里只放一个参数位，你可以自己拼进去）
#     user_data_arg: Optional[str] = None
#
#
# # --------------------------------
# # Selenium：创建浏览器 driver
# # --------------------------------
# def build_driver(cfg: RunConfig) -> webdriver.Chrome:
#     options = Options()
#
#     # 指定 chrome 可执行文件（你是 portable chrome，所以需要）
#     options.binary_location = cfg.chrome_binary
#
#     # 是否无头
#     if cfg.headless:
#         options.add_argument("--headless=new")
#
#     # 常用稳定参数
#     options.add_argument("--start-maximized")
#     options.add_argument("--no-sandbox")
#
#     # 关闭缓存（你做网络采集/抓包时通常希望减少缓存干扰）
#     options.add_argument("--disable-application-cache")
#     options.add_argument("--disk-cache-size=0")
#     options.add_argument("--dns-prefetch-disable")
#
#     # 如果指定了 user-data-dir/profile，则复用登录态/环境
#     if cfg.user_data_arg:
#         options.add_argument(cfg.user_data_arg)
#
#     # 指定 chromedriver
#     service = Service(cfg.chromedriver_path)
#     driver = webdriver.Chrome(service=service, options=options)
#
#     # 页面加载超时
#     driver.set_page_load_timeout(60)
#     return driver
#
#
# # --------------------------------
# # Selenium：更稳的点击（失败则尝试 JS click）
# # --------------------------------
# def safe_click(driver, element) -> bool:
#     try:
#         # 先滚动到可视区域
#         # driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
#         time.sleep(0.1)
#         element.click()
#         return True
#     except Exception:
#         # 正常 click 失败（被遮挡等），就尝试 JS click
#         try:
#             driver.execute_script("arguments[0].click();", element)
#             return True
#         except Exception:
#             return False
#
#
# # --------------------------------
# # Selenium：用 xpath 定位并点击（带等待）
# # --------------------------------
# def try_click_by_xpath(driver, xpath: str, timeout: int = 3) -> bool:
#     try:
#         el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
#         return safe_click(driver, el)
#     except Exception:
#         return False
#
#
# # --------------------------------
# # 让播放器底部控件显示（鼠标轻微移动）
# # 有些播放器控件只有 hover 才会出现（你截图里右下角画质就是）
# # --------------------------------
# def move_mouse_fixed(x=1602, y=1200, duration=10):
#     pyautogui.FAILSAFE = True
#     pyautogui.moveTo(x, y, duration=duration)
#     print(f"moved to ({x}, {y})")
#
# ############
# # 确保悬浮窗一直存在
# #############
# def start_quality_hover_keepalive(driver, interval_ms: int = 300):
#     driver.execute_script(f"""
#     try {{
#       if (window.__qKeepAlive) clearInterval(window.__qKeepAlive);
#       window.__qKeepAlive = setInterval(() => {{
#         const btn = document.querySelector('[data-e2e="quality"]');
#         const panel = document.querySelector('[data-e2e="quality-selector"]');
#
#         // 优先对“面板”续命；面板没显示就对按钮续命
#         const el = (panel && panel.offsetParent) ? panel : btn;
#         if (!el) return;
#
#         const r = el.getBoundingClientRect();
#         const x = Math.floor(r.left + Math.min(10, Math.max(1, r.width - 2)));
#         const y = Math.floor(r.top  + Math.min(10, Math.max(1, r.height - 2)));
#
#         ['mousemove','mouseover','mouseenter'].forEach(type => {{
#           el.dispatchEvent(new MouseEvent(type, {{bubbles:true, clientX:x, clientY:y}}));
#         }});
#       }}, {interval_ms});
#     }} catch (e) {{}}
#     """)
#
# def stop_quality_hover_keepalive(driver):
#     driver.execute_script("""
#     try {
#       if (window.__qKeepAlive) clearInterval(window.__qKeepAlive);
#       window.__qKeepAlive = null;
#     } catch (e) {}
#     """)
#
# def open_quality_menu(driver, timeout: int = 6) -> bool:
#     try:
#         start_quality_hover_keepalive(driver)  # ✅ 先续命，防止菜单闪退
#
#         qbtn = WebDriverWait(driver, timeout).until(
#             EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-e2e="quality"]'))
#         )
#         driver.execute_script("arguments[0].click();", qbtn)
#
#         WebDriverWait(driver, timeout).until(
#             EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="quality-selector"]'))
#         )
#         return True
#     except Exception:
#         return False
#
# """
#     在 quality-selector 面板内找到某个文案对应的“可点击行容器”。
#     先精确匹配，再匹配 自动(原画) 这种 startswith。
# """
# def _find_clickable_for_label(panel, label: str):
#
#     # 1) 精确匹配文本（原画/高清/标清）
#     xpath_exact = f".//*[normalize-space(text())='{label}']"
#     nodes = panel.find_elements(By.XPATH, xpath_exact)
#
#     # 2) 自动的特殊：自动(原画)/自动(高清)
#     if (not nodes) and label == "自动":
#         xpath_auto = ".//*[starts-with(normalize-space(text()),'自动')]"
#         nodes = panel.find_elements(By.XPATH, xpath_auto)
#
#     if not nodes:
#         return None
#
#     # 从文本节点向上找可点击容器：优先 Igg37jeS（即便类名变，也会有 role/cursor/onclick 等）
#     text_node = nodes[0]
#
#     # 优先：最近的带 onclick 的元素
#     candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::*[@onclick][1]")
#     if candidates:
#         return candidates[0]
#
#     # 其次：最近的 aria-role=menuitem / button
#     candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::*[@role='menuitem' or @role='button'][1]")
#     if candidates:
#         return candidates[0]
#
#     # 其次：最近的 div（通常就是一行选项的容器）
#     candidates = text_node.find_elements(By.XPATH, "./ancestor-or-self::div[1]")
#     if candidates:
#         return candidates[0]
#
#     return None
# ##########
# # 自动选择画质
# ############
# def select_quality(driver, preferred=("原画", "高清", "标清", "自动"), timeout: int = 6):
#     try:
#         start_quality_hover_keepalive(driver)
#
#         if not open_quality_menu(driver, timeout=timeout):
#             return None
#
#         panel = WebDriverWait(driver, timeout).until(
#             EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-e2e="quality-selector"]'))
#         )
#
#         # 可选：打印一下面板里的所有可见文本，方便你排查文案变动
#         # print(panel.text)
#
#         for q in preferred:
#             el = _find_clickable_for_label(panel, q)
#             if el and el.is_displayed():
#                 driver.execute_script("arguments[0].click();", el)
#                 time.sleep(0.2)
#                 return q
#
#         return None
#     finally:
#         stop_quality_hover_keepalive(driver)
#
# # --------------------------------
# # 纯 Selenium 获取分类：
# # 从首页抓取 a[href]，筛选包含 category_name / activity_name 等参数的链接
# # 返回：{category_url: category_name}
# # --------------------------------
# def get_categories_selenium(driver) -> Dict[str, str]:
#     driver.get(LIVE_HOME)
#
#     # 等待页面完成加载
#     WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
#     time.sleep(2)
#
#     cats: Dict[str, str] = {}
#
#     # 抓取所有链接
#     anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
#     for a in anchors:
#         href = (a.get_attribute("href") or "").strip()
#         text = (a.text or "").strip()
#
#         # 必须有 href 和可见文字
#         if not href or not text:
#             continue
#
#         # 过滤：必须是 live.douyin.com 且含 category / category_name / activity_name
#         if "live.douyin.com" in href and ("category" in href or "category_name" in href or "activity_name" in href):
#             # 去重：限制文本长度，避免把很长的标题也当分类
#             if href not in cats and len(text) <= 10:
#                 cats[href] = text
#
#     return cats
#
#
# # --------------------------------
# # 分类页滚动加载更多直播卡片
# # --------------------------------
# def scroll_to_load(driver, rounds: int = 8):
#     for _ in range(rounds):
#         driver.execute_script("window.scrollBy(0, document.documentElement.clientHeight * 0.9);")
#         time.sleep(0.8)
#
#
# # --------------------------------
# # 从分类页获取直播间链接：
# # 打开分类页 -> 滚动 -> 收集 live.douyin.com/数字
# # --------------------------------
# def get_live_rooms_in_category(driver, category_url: str, limit: int = 10) -> List[str]:
#     driver.get(category_url)
#
#     WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
#     time.sleep(2)
#
#     rooms: Set[str] = set()
#
#     # 最多循环多次：每次抓链接 + 滚动一屏
#     for _ in range(10):
#         anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
#         for a in anchors:
#             href = (a.get_attribute("href") or "").strip()
#
#             # 只要符合直播间格式就加入
#             if ROOM_RE.match(href):
#                 # 去掉 query 参数，避免重复（例如 ?activity_name=...）
#                 rooms.add(href.split("?")[0])
#
#                 # 达到数量就返回
#                 if len(rooms) >= limit:
#                     return list(rooms)[:limit]
#
#         # 本轮没够，继续滚动加载
#         scroll_to_load(driver, rounds=1)
#
#     return list(rooms)[:limit]
#
#
# # --------------------------------
# # 启动 tshark 抓包（返回进程对象）
# # --------------------------------
# def start_tshark_capture(cfg: RunConfig, filepath: str, duration: int) -> subprocess.Popen:
#     tshark_cmd = [
#         "tshark",
#         "-q",                           # 安静模式（减少输出）
#         "-a", f"duration:{duration}",   # 自动抓 duration 秒后停止
#         "-w", filepath,                 # 输出 pcap 文件
#         "-i", cfg.network_iface,        # 网卡
#     ]
#
#     # stdout/stderr 不输出到控制台
#     return subprocess.Popen(tshark_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#
#
# # --------------------------------
# # 对一个直播间执行：抓包 + 打开 + 选画质 + 停留
# # --------------------------------
# def run_capture_session(cfg: RunConfig, category_name: str, room_url: str, driver: webdriver.Chrome):
#     os.makedirs(cfg.pcap_dir, exist_ok=True)
#
#     timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#     safe_cat = re.sub(r"[\\/:*?\"<>|]", "_", category_name or "unknown")
#
#     # ✅ 先用临时文件名开抓包，保证“全程流量”都抓到
#     tmp_filename = f"{safe_cat}_pending_{timestamp}.pcap"
#     tmp_filepath = os.path.join(cfg.pcap_dir, tmp_filename)
#
#     duration = cfg.dwell_seconds + cfg.tshark_extra_seconds
#
#     tshark_proc = None
#     picked = None
#     try:
#         # 1) 先启动 tshark（全程抓包）
#         tshark_proc = start_tshark_capture(cfg, tmp_filepath, duration)
#         print(f"▶️ 开始抓包(临时): {tmp_filename}")
#
#         # 2) 再打开直播间
#         driver.get(room_url)
#         time.sleep(5)
#
#         print("加载完开始选择画质")
#         # start_mouse_shake_for_driver(driver, seconds=10)
#
#         picked = select_quality(driver, preferred=cfg.preferred_qualities)
#         # picked = select_quality_douyin(driver, preferred=cfg.preferred_qualities)
#         print(f"🎚️ 画质选择结果: {picked}")
#
#         # 3) 停留指定时间
#         print(f"🖥️ 停留 {cfg.dwell_seconds}s: {room_url}")
#         end_t = time.time() + cfg.dwell_seconds
#         while time.time() < end_t:
#             # hover_player(driver)
#             time.sleep(1.5)
#
#     finally:
#         # 4) 先确保 tshark 已经结束并释放文件句柄
#         if tshark_proc:
#             try:
#                 tshark_proc.wait(timeout=15)
#             except Exception:
#                 tshark_proc.terminate()
#                 try:
#                     tshark_proc.wait(timeout=5)
#                 except Exception:
#                     pass
#
#         # 5) tshark 结束后再改名，把 picked 加进文件名
#         safe_picked = re.sub(r"[\\/:*?\"<>|]", "_", (picked or "unknown"))
#         safe_picked = safe_picked.replace(" ", "")  # 可选：去空格
#         final_filename = f"{safe_cat}_{safe_picked}_{timestamp}.pcap"
#         final_filepath = os.path.join(cfg.pcap_dir, final_filename)
#
#         try:
#             # 防止同名覆盖（极少见），加个随机后缀
#             if os.path.exists(final_filepath):
#                 suffix = random.randint(1000, 9999)
#                 final_filename = f"{safe_cat}_{safe_picked}_{timestamp}_{suffix}.pcap"
#                 final_filepath = os.path.join(cfg.pcap_dir, final_filename)
#
#             os.rename(tmp_filepath, final_filepath)
#             print(f"🛑 抓包已保存: {final_filepath}\n")
#
#
#         except Exception as e:
#             # 改名失败就保留临时文件
#             print(f"⚠️ 改名失败，保留临时文件: {tmp_filepath}，原因: {e}\n")
# # --------------------------------
# # 主流程：获取分类 -> 选分类 -> 抓直播间 -> 逐个抓包
# # --------------------------------
# def main():
#     # 运行参数在这里配置
#     cfg = RunConfig(
#         chrome_binary=r"chrome-win64/chrome.exe",
#         chromedriver_path=r"../chromedriver-win64/chromedriver-win64/chromedriver.exe",
#         network_iface="WLAN",
#         pcap_dir="../captures",
#         rooms_per_category=8,
#         dwell_seconds=60,
#         tshark_extra_seconds=5,
#         preferred_qualities=("原画", "高清", "标清", "自动"),
#         headless=False,
#
#         # 如果你要复用登录态，就填这个
#         # user_data_arg=r"--user-data-dir=C:\Users\xxx\AppData\Local\Google\Chrome\User Data"
#         user_data_arg="user-data-dir=C:\\Users\WangH\AppData\Local\Google\Chrome for Testing\\User Data",
#     )
#
#     driver = build_driver(cfg)
#     try:
#         # 1) 从首页尝试自动解析分类
#         categories = get_categories_selenium(driver)
#
#         # 2) 如果抓到了分类，就让用户选；否则让用户手动粘贴分类 URL
#         if categories:
#             print("检测到分类（可能不全）：")
#             items = list(categories.items())
#             for i, (u, name) in enumerate(items, 1):
#                 print(f"{i}. {name}  |  {u}")
#
#             print("\n输入序号选择分类；或直接粘贴分类URL：")
#             choice = input().strip()
#             # choice = "1"
#
#             if choice.isdigit() and 1 <= int(choice) <= len(items):
#                 category_url, category_name = items[int(choice) - 1]
#             else:
#                 category_url = choice
#                 category_name = "manual"
#         else:
#             print("未能自动识别分类链接（页面结构可能更新）。请直接粘贴分类URL：")
#             category_url = input().strip()
#             category_name = "manual"
#
#         # 3) 进入分类页抓直播间列表
#         rooms = get_live_rooms_in_category(driver, category_url, limit=cfg.rooms_per_category)
#         print(f"\n分类 [{category_name}] 抓到直播间数量: {len(rooms)}")
#         for r in rooms:
#             print(" -", r)
#
#             # 4) 逐个直播间：抓包 + 选画质 + 停留
#             for idx, room_url in enumerate(rooms, 1):
#                 try:
#                     print(f"\n===== [{idx}/{len(rooms)}] 开始采集: {room_url} =====")
#                     run_capture_session(cfg, category_name, room_url, driver)
#                 except Exception as e:
#                     # 这里千万别 raise，让它继续下一个直播间
#                     print(f"❌ 直播间采集失败，跳过: {room_url}")
#                     print(f"   异常类型: {type(e).__name__}")
#                     print(f"   异常信息: {e}")
#
#                     # 可选：失败后回到首页/分类页，减少 driver 卡死的概率
#                     try:
#                         driver.switch_to.default_content()
#                     except Exception:
#                         pass
#
#                     # 可选：给页面/驱动一个喘息时间
#                     time.sleep(2)
#                     continue
#
#     finally:
#         driver.quit()
#
#
#
#
#
#
#
# # 入口
# if __name__ == "__main__":
#     i = 0
#     while True:
#         i += 1
#         try:
#             print(f"第 {i} 次运行开始")
#             main()
#             print(f"第 {i} 次运行结束")
#         except Exception as e:
#             print(f"第 {i} 次运行报错：{e}")
#             traceback.print_exc()
#         time.sleep(1)  # 可调：每次间隔 1 秒


import os
import re
import time
import subprocess
import traceback
from datetime import datetime
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
