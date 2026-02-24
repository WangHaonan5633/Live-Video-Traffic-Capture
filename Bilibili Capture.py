#
# import os
# import re
# import time
# import subprocess
# from datetime import datetime
# from dataclasses import dataclass
# from typing import Dict, List, Tuple, Optional, Set
# import pyautogui
# import random
# import threading
# from typing import Optional, Sequence
# # Selenium 相关
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.common.action_chains import ActionChains
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
#
#
# # 抖音直播首页
# LIVE_HOME = "https://live.bilibili.com/"
#
# # 用于匹配直播间链接：live.douyin.com/数字
# ROOM_RE = re.compile(r"^https?://live\.bilibili\.com/\d+")
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
#     # options.add_argument("--force-device-scale-factor=1")
#     # options.add_argument("--high-dpi-support=1")
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
# def start_bili_hover_keepalive(driver, interval_ms: int = 250):
#     driver.execute_script(f"""
#     try {{
#       if (window.__biliKeepAlive) clearInterval(window.__biliKeepAlive);
#       window.__biliKeepAlive = setInterval(() => {{
#         const panel = document.querySelector('div.quality-wrap div.panel');
#         const btn = document.querySelector('div.quality-wrap .text.selected-qn')
#                   || document.querySelector('.bpx-player-ctrl-btn.bpx-player-ctrl-quality')
#                   || document.querySelector('.bpx-player');
#
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
#     }} catch(e) {{}}
#     """)
#
# def stop_bili_hover_keepalive(driver):
#     driver.execute_script("""
#     try {
#       if (window.__biliKeepAlive) clearInterval(window.__biliKeepAlive);
#       window.__biliKeepAlive = null;
#     } catch(e) {}
#     """)
# def _find_visible_video_in_current_doc(driver):
#     vids = driver.find_elements(By.CSS_SELECTOR, "video")
#     # 取第一个可见的 video（也可以按 size 选最大）
#     for v in vids:
#         try:
#             if v.is_displayed():
#                 return v
#         except Exception:
#             pass
#     return None
#
#
# def _find_visible_video_anywhere(driver):
#     # 1) 顶层先找
#     driver.switch_to.default_content()
#     v = _find_visible_video_in_current_doc(driver)
#     if v:
#         return v
#
#     # 2) 扫描所有 iframe
#     iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
#     for i, f in enumerate(iframes):
#         try:
#             driver.switch_to.default_content()
#             driver.switch_to.frame(f)
#             v = _find_visible_video_in_current_doc(driver)
#             if v:
#                 return v
#         except Exception:
#             continue
#
#     driver.switch_to.default_content()
#     return None
#
# def scroll_until_video_appears(driver, timeout=20, step=900):
#     end = time.time() + timeout
#
#     while time.time() < end:
#         v = _find_visible_video_anywhere(driver)
#         if v:
#             # 注意：如果 video 在 iframe 里，此时 driver 已经切到对应 frame 了
#             driver.execute_script(
#                 "arguments[0].scrollIntoView({block:'center', inline:'center'});", v
#             )
#             return v
#
#         # 没找到就往下滚（滚 window）
#         driver.switch_to.default_content()
#         driver.execute_script("window.scrollBy(0, arguments[0]);", step)
#         time.sleep(0.35)
#
#     raise TimeoutError("滚动后仍未找到 video（可能在更深层 iframe / 或不使用 video 标签渲染）")
#
#
# def click_quality_item_fast(driver, keyword: str) -> bool:
#     # 返回 True 表示找到了并点击了（不代表已经切流完成）
#     js = r"""
#     const kw = arguments[0];
#     const panel = document.querySelector("div.quality-wrap div.panel");
#     if (!panel || !panel.offsetParent) return false;
#
#     const items = Array.from(panel.querySelectorAll("div.list-it"));
#     // 过滤“画质增强”
#     const cands = items.filter(it => it && it.innerText && !it.innerText.includes("画质增强"));
#
#     // 先精确包含匹配（如 原画/蓝光/超清/高清/自动）
#     let target = cands.find(it => it.innerText.includes(kw));
#
#     // “自动”可能显示“自动”或“跟随”之类，必要时可扩展
#     if (!target && kw === "自动") {
#       target = cands.find(it => it.innerText.includes("自动")) || cands.find(it => it.innerText.includes("跟随"));
#     }
#
#     if (!target) return false;
#     target.click();
#     return true;
#     """
#     try:
#         return bool(driver.execute_script(js, keyword))
#     except Exception:
#         return False
#
#
# def wait_quality_changed_fast(driver, keyword: str, timeout=2.5) -> bool:
#     wait = fast_wait(driver, timeout)
#     try:
#         # 直接等右下角文字包含 keyword
#         return wait.until(lambda d: keyword in get_current_quality_text(d))
#     except Exception:
#         return False
# def fast_wait(driver, timeout=2):
#     return WebDriverWait(driver, timeout, poll_frequency=0.08)
# def open_quality_menu_fast(driver, timeout: int = 2) -> bool:
#     wait = fast_wait(driver, timeout)
#
#     # 让控件出现：move 到播放器即可（不需要 pause 很久）
#     try:
#         player = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".bpx-player-container, .bpx-player, video")))
#         ActionChains(driver).move_to_element(player).perform()
#     except Exception:
#         pass
#
#     # 面板已经开了直接返回
#     try:
#         panel = driver.find_element(By.CSS_SELECTOR, "div.quality-wrap div.panel")
#         if panel.is_displayed():
#             return True
#     except Exception:
#         pass
#
#     # 直接 JS click 入口（比 ActionChains click 更快也更抗遮挡）
#     for sel in ["div.quality-wrap .text.selected-qn", ".bpx-player-ctrl-btn.bpx-player-ctrl-quality", ".bpx-player-ctrl-quality"]:
#         try:
#             el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
#             driver.execute_script("arguments[0].click();", el)
#             break
#         except Exception:
#             continue
#
#     try:
#         wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.quality-wrap div.panel")))
#         return True
#     except Exception:
#         return False
# def get_quality_panel(driver, timeout=5):
#     return WebDriverWait(driver, timeout).until(
#         EC.visibility_of_element_located((By.CSS_SELECTOR, "div.quality-wrap div.panel"))
#     )
# # 获得当前的画质文本
# def get_current_quality_text(driver, timeout=5) -> str:
#     el = WebDriverWait(driver, timeout).until(
#         EC.presence_of_element_located((By.CSS_SELECTOR, "div.quality-wrap .text.selected-qn"))
#     )
#     return el.text.strip()
#
#
# # 选择画质
# def click_quality_item(driver, panel, keyword: str, timeout=3) -> bool:
#     # keyword: "原画"/"蓝光"/"超清"/"自动"
#     # 在 panel 内找 list-it（排除“画质增强”那一行：它里面有子结构，不是纯文字）
#     items = panel.find_elements(By.CSS_SELECTOR, "div.list-it")
#     target = None
#     for it in items:
#         txt = it.text.strip()
#         if not txt:
#             continue
#         # 过滤“画质增强”那行
#         if "画质增强" in txt:
#             continue
#         if keyword in txt:
#             target = it
#             break
#
#     if not target:
#         return False
#
#     # 用 ActionChains 更像真实点击（比 element.click 更稳）
#     ActionChains(driver).move_to_element(target).pause(0.05).click(target).perform()
#     return True
#
# def wait_quality_changed(driver, keyword: str, timeout=5) -> bool:
#     # 等右下角“当前画质”文字变化
#     try:
#         WebDriverWait(driver, timeout).until(lambda d: keyword in get_current_quality_text(d))
#         return True
#     except Exception:
#         return False
#
# from selenium.common.exceptions import StaleElementReferenceException
#
# from selenium.common.exceptions import StaleElementReferenceException
#
# def select_quality_fast(driver, preferred=("原画", "蓝光", "超清", "高清", "自动")):
#     start_bili_hover_keepalive(driver, interval_ms=200)  # 续命频率可以稍微快点
#     try:
#         for q in preferred:
#             for _ in range(2):  # 每档最多试两次：比长等待更快
#                 if not open_quality_menu_fast(driver, timeout=2):
#                     continue
#
#                 if not click_quality_item_fast(driver, q):
#                     continue
#
#                 if wait_quality_changed_fast(driver, q, timeout=2.5):
#                     return q
#
#                 # 没切成功：马上重开面板再点一次
#                 # （有时第一次点到了，但文字更新慢；第二次就稳定）
#             # 这个 q 失败就换下一个
#         return None
#     finally:
#         stop_bili_hover_keepalive(driver)
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
#         # 过滤：必须是 live.bilibili.com且含 category / category_name / activity_name
#         if "live.bilibili.com" in href and ("category" in href or "category_name" in href or "activity_name" in href):
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
#         video = scroll_until_video_appears(driver)
#         picked = select_quality_fast(driver, preferred=cfg.preferred_qualities)
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
#             # move_mouse_fixed(x=1541, y=200, duration=3)
#
#         except Exception as e:
#             # 改名失败就保留临时文件
#             print(f"⚠️ 改名失败，保留临时文件: {tmp_filepath}，原因: {e}\n")
#             # move_mouse_fixed(x=1541, y=200, duration=3)
#
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
#             #聊天室： https://live.bilibili.com/p/eden/area-tags?parentAreaId=14&areaId=0&visit_id=30
#             #娱乐：https://live.bilibili.com/p/eden/area-tags?parentAreaId=1&areaId=0&visit_id=3
#             #网游：https://live.bilibili.com/p/eden/area-tags?parentAreaId=2&areaId=0&visit_id=1
#             #手游：https://live.bilibili.com/p/eden/area-tags?parentAreaId=3&areaId=0&visit_id=1
#             #单机游戏：https://live.bilibili.com/p/eden/area-tags?parentAreaId=6&areaId=0&visit_id=1
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
#             print("以下是常用分类URL，请选择或输入自定义URL：")
#             print("- 聊天室: https://live.bilibili.com/p/eden/area-tags?parentAreaId=14&areaId=0&visit_id=30")
#             print("- 娱乐: https://live.bilibili.com/p/eden/area-tags?parentAreaId=1&areaId=0&visit_id=3")
#             print("- 网游: https://live.bilibili.com/p/eden/area-tags?parentAreaId=2&areaId=0&visit_id=1")
#             print("- 手游: https://live.bilibili.com/p/eden/area-tags?parentAreaId=3&areaId=0&visit_id=1")
#             print("- 单机游戏: https://live.bilibili.com/p/eden/area-tags?parentAreaId=6&areaId=0&visit_id=1")
#             print("请直接粘贴分类URL：")
#
#             category_url = input().strip()
#
#             # 自动判断分类名称
#             if "parentAreaId=14" in category_url:
#                 category_name = "聊天室"
#             elif "parentAreaId=1" in category_url:
#                 category_name = "娱乐"
#             elif "parentAreaId=2" in category_url:
#                 category_name = "网游"
#             elif "parentAreaId=3" in category_url:
#                 category_name = "手游"
#             elif "parentAreaId=6" in category_url:
#                 category_name = "单机游戏"
#             else:
#                 category_name = "manual"
#
#             print(f"已设置分类: {category_name}")
#
#         # 3) 进入分类页抓直播间列表
#         rooms = get_live_rooms_in_category(driver, category_url, limit=cfg.rooms_per_category)
#         print(f"\n分类 [{category_name}] 抓到直播间数量: {len(rooms)}")
#         for r in rooms:
#             print(" -", r)
#
#         # 4) 逐个直播间：抓包 + 选画质 + 停留
#         for idx, room_url in enumerate(rooms, 1):
#             try:
#                 print(f"\n===== [{idx}/{len(rooms)}] 开始采集: {room_url} =====")
#                 run_capture_session(cfg, category_name, room_url, driver)
#             except Exception as e:
#                 # 这里千万别 raise，让它继续下一个直播间
#                 print(f"❌ 直播间采集失败，跳过: {room_url}")
#                 print(f"   异常类型: {type(e).__name__}")
#                 print(f"   异常信息: {e}")
#
#                 # 可选：失败后回到首页/分类页，减少 driver 卡死的概率
#                 try:
#                     driver.switch_to.default_content()
#                 except Exception:
#                     pass
#
#                 # 可选：给页面/驱动一个喘息时间
#                 time.sleep(2)
#                 continue
#
#     finally:
#         driver.quit()
# # 入口
# if __name__ == "__main__":
#     # for i in range(20):
#         main()
import os
import re
import time
import subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set
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

# ----------------------------
# 站点配置
# ----------------------------
LIVE_HOME = "https://live.bilibili.com/"
ROOM_RE = re.compile(r"^https?://live\.bilibili\.com/\d+")

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

    # ✅ 必须复用登录态：用同一个 user-data-dir
    # 写法务必带 -- 前缀：--user-data-dir=...
    user_data_arg: Optional[str] = None

    # 可选：固定 profile（例如 Default / Profile 1）
    # 如果你不确定，就先注释掉
    profile_directory: Optional[str] = None


# ----------------------------
# profile 锁处理（复用登录态 + 频繁重启必备）
# ----------------------------
def _profile_lock_files(user_data_dir: str) -> List[str]:
    # 这些文件一般在 user-data-dir 根目录（不是 Default 目录里）
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
# Selenium：创建浏览器 driver
# ----------------------------
def build_driver(cfg: RunConfig) -> webdriver.Chrome:
    options = Options()
    options.binary_location = cfg.chrome_binary

    if cfg.headless:
        options.add_argument("--headless=new")

    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")

    # 关闭缓存（减少缓存干扰）
    options.add_argument("--disable-application-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--dns-prefetch-disable")

    # ✅ 复用登录态
    if cfg.user_data_arg:
        options.add_argument(cfg.user_data_arg)

    if cfg.profile_directory:
        options.add_argument(f"--profile-directory={cfg.profile_directory}")

    service = Service(cfg.chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


def build_driver_with_retry(cfg: RunConfig, retries: int = 4, backoff: float = 1.2) -> webdriver.Chrome:
    """
    复用同一个 user-data-dir 时，频繁重启很容易遇到 profile 被占用。
    这里做：等待释放 + 重试 + 必要时清锁（仅脚本专用 profile 时建议）。
    """
    last_err = None
    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    for i in range(retries):
        try:
            if user_data_dir:
                wait_profile_released(user_data_dir, timeout=8.0)
            return build_driver(cfg)

        except WebDriverException as e:
            last_err = e
            msg = str(e).lower()

            # 常见：profile 被占用 / 没释放
            if ("user data directory is already in use" in msg) or ("profile" in msg and "in use" in msg):
                print(f"⚠️ profile 仍被占用，重试启动({i+1}/{retries})...")
                time.sleep(backoff * (i + 1))

                # 第二次及以后仍失败：尝试清锁（仅脚本专用 profile）
                if user_data_dir and i >= 1:
                    cleanup_profile_locks_if_needed(user_data_dir)

                continue

            raise

    raise last_err


# ----------------------------
# B站播放器：画质选择（你原来的逻辑）
# ----------------------------
def start_bili_hover_keepalive(driver, interval_ms: int = 250):
    driver.execute_script(f"""
    try {{
      if (window.__biliKeepAlive) clearInterval(window.__biliKeepAlive);
      window.__biliKeepAlive = setInterval(() => {{
        const panel = document.querySelector('div.quality-wrap div.panel');
        const btn = document.querySelector('div.quality-wrap .text.selected-qn')
                  || document.querySelector('.bpx-player-ctrl-btn.bpx-player-ctrl-quality')
                  || document.querySelector('.bpx-player');

        const el = (panel && panel.offsetParent) ? panel : btn;
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


def stop_bili_hover_keepalive(driver):
    driver.execute_script("""
    try {
      if (window.__biliKeepAlive) clearInterval(window.__biliKeepAlive);
      window.__biliKeepAlive = null;
    } catch(e) {}
    """)


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
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", v)
            return v

        driver.switch_to.default_content()
        driver.execute_script("window.scrollBy(0, arguments[0]);", step)
        time.sleep(0.35)

    raise TimeoutError("滚动后仍未找到 video（可能在更深层 iframe / 或不使用 video 标签渲染）")


def fast_wait(driver, timeout=2):
    return WebDriverWait(driver, timeout, poll_frequency=0.08)


def open_quality_menu_fast(driver, timeout: int = 2) -> bool:
    wait = fast_wait(driver, timeout)

    try:
        player = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".bpx-player-container, .bpx-player, video"))
        )
        ActionChains(driver).move_to_element(player).perform()
    except Exception:
        pass

    try:
        panel = driver.find_element(By.CSS_SELECTOR, "div.quality-wrap div.panel")
        if panel.is_displayed():
            return True
    except Exception:
        pass

    for sel in [
        "div.quality-wrap .text.selected-qn",
        ".bpx-player-ctrl-btn.bpx-player-ctrl-quality",
        ".bpx-player-ctrl-quality",
    ]:
        try:
            el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            driver.execute_script("arguments[0].click();", el)
            break
        except Exception:
            continue

    try:
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.quality-wrap div.panel")))
        return True
    except Exception:
        return False


def get_current_quality_text(driver, timeout=5) -> str:
    el = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.quality-wrap .text.selected-qn"))
    )
    return el.text.strip()


def click_quality_item_fast(driver, keyword: str) -> bool:
    js = r"""
    const kw = arguments[0];
    const panel = document.querySelector("div.quality-wrap div.panel");
    if (!panel || !panel.offsetParent) return false;

    const items = Array.from(panel.querySelectorAll("div.list-it"));
    const cands = items.filter(it => it && it.innerText && !it.innerText.includes("画质增强"));
    let target = cands.find(it => it.innerText.includes(kw));

    if (!target && kw === "自动") {
      target = cands.find(it => it.innerText.includes("自动")) || cands.find(it => it.innerText.includes("跟随"));
    }

    if (!target) return false;
    target.click();
    return true;
    """
    try:
        return bool(driver.execute_script(js, keyword))
    except Exception:
        return False


def wait_quality_changed_fast(driver, keyword: str, timeout=2.5) -> bool:
    wait = fast_wait(driver, timeout)
    try:
        return wait.until(lambda d: keyword in get_current_quality_text(d))
    except Exception:
        return False


def select_quality_fast(driver, preferred=("原画", "蓝光", "超清", "高清", "自动")):
    start_bili_hover_keepalive(driver, interval_ms=200)
    try:
        for q in preferred:
            for _ in range(2):
                if not open_quality_menu_fast(driver, timeout=2):
                    continue
                if not click_quality_item_fast(driver, q):
                    continue
                if wait_quality_changed_fast(driver, q, timeout=2.5):
                    return q
        return None
    finally:
        stop_bili_hover_keepalive(driver)


# ----------------------------
# 分类/房间抓取
# ----------------------------
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
        if "live.bilibili.com" in href and ("category" in href or "category_name" in href or "activity_name" in href):
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
# ✅ 每个直播间：先确保没有浏览器（上一轮已 quit），再启动浏览器输入直播间 URL
# 并且：必须复用同一个 user-data-dir 登录态
# ----------------------------
def run_capture_session(cfg: RunConfig, category_name: str, room_url: str):
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

        # 2) ✅ 启动“全新浏览器实例”，但复用同一个登录态 profile
        driver = build_driver_with_retry(cfg)

        # 3) ✅ 输入直播间网址（driver.get）
        driver.get(room_url)
        time.sleep(5)

        print("加载完开始选择画质")
        scroll_until_video_appears(driver)
        picked = select_quality_fast(driver, preferred=cfg.preferred_qualities)
        print(f"🎚️ 画质选择结果: {picked}")

        # 4) 停留
        print(f"🖥️ 停留 {cfg.dwell_seconds}s: {room_url}")
        end_t = time.time() + cfg.dwell_seconds
        while time.time() < end_t:
            time.sleep(1.5)

    finally:
        # ✅ 先关浏览器（确保下一个房间启动前已关闭）
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

        # tshark 结束后再改名，把 picked 加进文件名
        safe_picked = re.sub(r"[\\/:*?\"<>|]", "_", (picked or "unknown"))
        safe_picked = safe_picked.replace(" ", "")
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
        chrome_binary=r"D:\Undergraduate_study\Project\LiveTafficCapture\chrome-win64\chrome.exe",
        chromedriver_path=r"D:\Undergraduate_study\Project\LiveTafficCapture\chromedriver-win64\chromedriver-win64\chromedriver.exe",
        network_iface="WLAN",
        pcap_dir="captures",
        rooms_per_category=8,
        dwell_seconds=60,
        tshark_extra_seconds=5,
        preferred_qualities=("原画", "高清", "标清", "自动"),
        headless=False,

        # ✅ 必须复用登录态：务必带 --
        user_data_arg=r"--user-data-dir=C:\Users\WangH\AppData\Local\Google\Chrome for Testing\User Data",

        # 可选：如果你的登录态在 Profile 1，就写 Profile 1；默认一般是 Default
        profile_directory="Default",
    )

    # 先用一个 driver 抓分类/房间列表（抓完就关，释放 profile）
    driver = build_driver_with_retry(cfg)
    user_data_dir = get_user_data_dir_from_arg(cfg.user_data_arg or "")

    try:
        categories = get_categories_selenium(driver)

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
            print("以下是常用分类URL，请选择或输入自定义URL：")
            print("- 聊天室: https://live.bilibili.com/p/eden/area-tags?parentAreaId=14&areaId=0&visit_id=30")
            print("- 娱乐: https://live.bilibili.com/p/eden/area-tags?parentAreaId=1&areaId=0&visit_id=3")
            print("- 网游: https://live.bilibili.com/p/eden/area-tags?parentAreaId=2&areaId=0&visit_id=1")
            print("- 手游: https://live.bilibili.com/p/eden/area-tags?parentAreaId=3&areaId=0&visit_id=1")
            print("- 单机游戏: https://live.bilibili.com/p/eden/area-tags?parentAreaId=6&areaId=0&visit_id=1")
            print("请直接粘贴分类URL：")
            category_url = input().strip()

            if "parentAreaId=14" in category_url:
                category_name = "聊天室"
            elif "parentAreaId=1" in category_url:
                category_name = "娱乐"
            elif "parentAreaId=2" in category_url:
                category_name = "网游"
            elif "parentAreaId=3" in category_url:
                category_name = "手游"
            elif "parentAreaId=6" in category_url:
                category_name = "单机游戏"
            else:
                category_name = "manual"

            print(f"已设置分类: {category_name}")

        rooms = get_live_rooms_in_category(driver, category_url, limit=cfg.rooms_per_category)
        print(f"\n分类 [{category_name}] 抓到直播间数量: {len(rooms)}")
        for r in rooms:
            print(" -", r)

    finally:
        # ✅ 抓列表结束立即关闭浏览器，释放 profile，让后续每房间重启顺利
        try:
            driver.quit()
        except Exception:
            pass
        if user_data_dir:
            wait_profile_released(user_data_dir, timeout=12.0)

    # ✅ 逐个直播间：每次都“先没有浏览器（上一轮已关）→ 再启动浏览器 → 输入URL”
    for idx, room_url in enumerate(rooms, 1):
        try:
            print(f"\n===== [{idx}/{len(rooms)}] 开始采集: {room_url} =====")
            run_capture_session(cfg, category_name, room_url)
        except Exception as e:
            print(f"❌ 直播间采集失败，跳过: {room_url}")
            print(f"   异常类型: {type(e).__name__}")
            print(f"   异常信息: {e}")
            time.sleep(2)
            continue


if __name__ == "__main__":
    main()
