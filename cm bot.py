import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import sys
import re
import random
import asyncio
import threading
import pandas as pd
from playwright.async_api import async_playwright

# ==================== CONFIGURATION & HELPER FUNCTIONS ====================
SCROLL_COUNT = 8  
FILE_NAME = "tumblr_communities.xlsx"  
POST_FILE_NAME = "posts.xlsx"  
TARGET_TOTAL_LINKS = 1000  
MIN_MEMBERS = 5  
MAX_JOIN_PER_ACCOUNT = 10  

ACTIVE_CONTEXTS = {}
ACCOUNT_STATUS_MAP = {}  # অ্যাকাউন্টের লাইভ স্ট্যাটাস ট্র্যাক করার ডিকশনারি

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--ignore-certificate-errors",
    "--disable-extensions",
    "--excludeSwitches=enable-automation",
    "--useAutomationExtension=false"
]

class RedirectText:
    """CMD এর print আউটপুট GUI এর টেক্সট উইজেটে রিডাইরেক্ট করার ক্লাস"""
    def __init__(self, text_widget, app_instance):
        self.text_widget = text_widget
        self.app_instance = app_instance

    def write(self, string):
        # লগগুলো মেমোরিতে জমিয়ে রাখা যাতে অন্য ট্যাবে গেলেও মুছে না যায়
        self.app_instance.terminal_logs_buffer += string
        def _insert():
            try:
                self.text_widget.insert(tk.END, string)
                self.text_widget.see(tk.END)
            except Exception:
                pass
        self.text_widget.after(0, _insert)

    def flush(self):
        pass

def safe_save_excel(df, target_path):
    """উইন্ডোজ ফাইল লক এবং হঠাৎ পাওয়ার কাট হ্যান্ডেল করার জন্য আরও সুরক্ষিত অ্যাটমিক সেভ"""
    temp_path = target_path.replace(".xlsx", "_temp.xlsx")
    backup_path = target_path.replace(".xlsx", "_backup.xlsx")
    
    try:
        # ১. প্রথমে একটি নতুন টেম্পোরারি ফাইলে ডাটা সেভ করুন
        df.to_excel(temp_path, index=False)
        
        # ২. যদি মেইন ফাইল আগে থেকেই থাকে, তবে তার ব্যাকআপ তৈরি করুন
        if os.path.exists(target_path):
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except:
                    pass
            try:
                os.replace(target_path, backup_path)
            except Exception as e:
                print(f"   ↳ [BACKUP WARNING]: Could not create backup file: {e}")
        
        # ৩. টেম্পোরারি ফাইলটিকে মেইন ফাইলে রূপান্তর করুন (Atomic Operation)
        os.replace(temp_path, target_path)
        
    except Exception as e:
        print(f"   ↳ [SAVE CRITICAL ERROR]: {e}")
        # যদি মেইন ফাইল নষ্ট হয়ে যায় কিন্তু ব্যাকআপ থাকে, তবে ব্যাকআপ রিস্টোর করার চেষ্টা করুন
        if os.path.exists(backup_path) and not os.path.exists(target_path):
            try:
                os.rename(backup_path, target_path)
            except:
                pass
        # টেম্প ফাইল পরিষ্কার করা
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def load_initial_tags(file_path="tag.txt"):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("art\nmarketing\nblog")
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

def load_all_accounts(file_path="account.txt"):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("email1@gmail.com:password123\nemail2@gmail.com:password456")
        return []
    accounts = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and ":" in line:
                email, password = line.split(":", 1)
                email = email.strip()
                accounts.append((email, password.strip()))
                if email not in ACCOUNT_STATUS_MAP:
                    ACCOUNT_STATUS_MAP[email] = "Not Logged In"
    return accounts

def load_threads_count(file_path="threads_count.txt"):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("5")
        return 5
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if content.isdigit():
            return max(1, int(content))
    return 5

def load_post_data():
    if not os.path.exists(POST_FILE_NAME):
        df = pd.DataFrame(columns=["Link", "Image"])
        df.loc[0] = ["https://www.google.com", "path_to_image.jpg"]
        df.to_excel(POST_FILE_NAME, index=False)
        return "https://www.google.com", "path_to_image.jpg"
    try:
        df_p = pd.read_excel(POST_FILE_NAME)
        link = "nan"
        image_path = "nan"
        
        if not df_p.empty:
            if "Link" in df_p.columns and len(df_p) > 0:
                link = str(df_p.iloc[0]["Link"]).strip()
            elif len(df_p.columns) > 0:
                link = str(df_p.iloc[0, 0]).strip()
                
            if "Image" in df_p.columns and len(df_p) > 0:
                image_path = str(df_p.iloc[0]["Image"]).strip()
            elif len(df_p.columns) > 1:
                image_path = str(df_p.iloc[0, 1]).strip()
                
        return link, image_path
    except Exception as e:
        print(f"[EXCEL LOAD ERROR]: {e}")
    return None, None

def parse_member_count(member_text):
    if not member_text:
        return 0
    member_text = member_text.lower().replace("members", "").replace("member", "").strip()
    try:
        if 'k' in member_text:
            num = float(member_text.replace('k', '').strip())
            return int(num * 1000)
        elif 'm' in member_text:
            num = float(member_text.replace('m', '').strip())
            return int(num * 1000000)
        else:
            digits = re.findall(r'\d+', member_text)
            return int(digits[0]) if digits else 0
    except Exception:
        return 0

# ==================== BOT CORE LOGIC ====================
async def login_tumblr(page, email, password):
    print(f"[AUTH] Checking session status for: {email}")
    try:
        await page.goto("https://www.tumblr.com/dashboard", wait_until="domcontentloaded")
        await page.wait_for_timeout(random.randint(3000, 5000))
        
        if "dashboard" in page.url and "login" not in page.url:
            print(f"[SUCCESS] Active session restored for: {email}")
            ACCOUNT_STATUS_MAP[email] = "No Restrictions"
            return True

        print(f"[AUTH] Logging in for: {email}")
        await page.goto("https://www.tumblr.com/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(random.randint(2000, 4000))
        
        await page.fill("input[name='email']", email)
        await page.wait_for_timeout(random.randint(1000, 2000))
        
        if await page.locator("button:has-text('Next')").is_visible():
            await page.click("button:has-text('Next')")
        else:
            await page.keyboard.press("Enter")
            
        await page.wait_for_timeout(random.randint(2500, 4000))
        await page.fill("input[name='password']", password)
        await page.wait_for_timeout(random.randint(1000, 2000))
        await page.keyboard.press("Enter")
        await page.wait_for_url("**/dashboard**", timeout=30000)
        print(f"[SUCCESS] Access granted for: {email}")
        ACCOUNT_STATUS_MAP[email] = "No Restrictions"
        return True
    except Exception:
        print(f"[CRITICAL] Authentication failed / Account issue for: {email}")
        ACCOUNT_STATUS_MAP[email] = "Restricted"
        return False

async def login_checker_worker(p, pixel_7, account_queue):
    while not account_queue.empty():
        email, password = await account_queue.get()
        base_session_dir = "accounts_sessions"
        if not os.path.exists(base_session_dir): os.makedirs(base_session_dir)
        user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))

        try:
            context = await p.chromium.launch_persistent_contextlaunch_persistent_context(
                user_data_dir=user_data_dir, headless=False, locale="en-US", timezone_id="Asia/Dhaka",
                viewport=pixel_7['viewport'], user_agent=pixel_7['user_agent'], args=STEALTH_ARGS
            )
            ACTIVE_CONTEXTS[email] = context
            page = context.pages[0] if context.pages else await context.new_page()

            is_ok = await login_tumblr(page, email, password)
            if is_ok:
                print(f"[CHECK PASSED] ✅ Account OK: {email}")
            else:
                print(f"[CHECK FAILED] ❌ Account BAD / Suspended: {email}")

            await context.close()
            if email in ACTIVE_CONTEXTS: del ACTIVE_CONTEXTS[email]
        except Exception as e:
            print(f"[CHECK ERROR] ❌ Could not check {email}: {e}")
            ACCOUNT_STATUS_MAP[email] = "Restricted"
            if email in ACTIVE_CONTEXTS:
                try: await ACTIVE_CONTEXTS[email].close()
                except: pass
                del ACTIVE_CONTEXTS[email]
        
        account_queue.task_done()

async def open_and_hold_session(p, pixel_7, email, password):
    base_session_dir = "accounts_sessions"
    if not os.path.exists(base_session_dir): os.makedirs(base_session_dir)
    user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))

    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir, headless=False, locale="en-US", timezone_id="Asia/Dhaka",
        viewport=pixel_7['viewport'], user_agent=pixel_7['user_agent'], args=STEALTH_ARGS
    )
    
    ACTIVE_CONTEXTS[email] = context
    page = context.pages[0] if context.pages else await context.new_page()

    await login_tumblr(page, email, password)
    await page.goto("https://www.tumblr.com/dashboard", wait_until="domcontentloaded")
    print(f"[OPEN] Profile opened for {email}.")

    try:
        while email in ACTIVE_CONTEXTS:
            if page.is_closed():
                break
            await asyncio.sleep(0.5)
    except Exception:
        pass
    finally:
        try:
            await context.close()
        except Exception:
            pass
        if email in ACTIVE_CONTEXTS:
            del ACTIVE_CONTEXTS[email]

async def handle_post_confirmation(page, email):
    try:
        post_btn = page.locator('button:has-text("Post now"), button[aria-label="Post now"], button:has-text("Post")').last
        if await post_btn.is_enabled():
            await post_btn.click()
            await asyncio.sleep(random.uniform(3.5, 5.0))
            
        confirm_dialog_btn = page.locator('button:has-text("Post")').filter(has_not_text="now").last
        if await confirm_dialog_btn.is_visible():
            await confirm_dialog_btn.click()
            await asyncio.sleep(random.uniform(3.5, 5.0))
            return True
    except: pass
    return False

async def finder_worker(p, pixel_7, account_queue, tag_queue, seen_links, df_lock, account_lock):
    while not account_queue.empty():
        if tag_queue.empty() or len(seen_links) >= TARGET_TOTAL_LINKS:
            break

        email, password = await account_queue.get()
        base_session_dir = "accounts_sessions"
        if not os.path.exists(base_session_dir): os.makedirs(base_session_dir)
        user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))

        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False, locale="en-US", timezone_id="Asia/Dhaka",
            viewport=pixel_7['viewport'], user_agent=pixel_7['user_agent'], args=STEALTH_ARGS
        )
        ACTIVE_CONTEXTS[email] = context
        page = context.pages[0] if context.pages else await context.new_page()

        if not await login_tumblr(page, email, password):
            await context.close()
            if email in ACTIVE_CONTEXTS: del ACTIVE_CONTEXTS[email]
            account_queue.task_done()
            continue

        while not tag_queue.empty() and len(seen_links) < TARGET_TOTAL_LINKS:
            if email not in ACTIVE_CONTEXTS: break
            tag = await tag_queue.get()
            formatted_tag = tag.replace(" ", "%20").replace("/", "%2F")
            community_url = f"https://www.tumblr.com/tagged/{formatted_tag}?sort=community"
            
            try:
                print(f"[{email}] Searching communities for tag: {tag}")
                await page.goto(community_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(3000, 5000))

                for _ in range(SCROLL_COUNT):
                    if email not in ACTIVE_CONTEXTS: break
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    await page.wait_for_timeout(random.randint(2000, 3500))

                extracted_data = await page.evaluate('''() => {
                    const elements = Array.from(document.querySelectorAll('a'));
                    let links = elements.map(a => {
                        let container = a.closest('article') || a.closest('div') || a;
                        return { 
                            href: a.href, 
                            text: a.innerText || "",
                            containerText: container.innerText || ""
                        };
                    });

                    let discoveredTags = [];
                    elements.forEach(a => {
                        let href = a.href || "";
                        if (href.includes('/tagged/')) {
                            let parts = href.split('/tagged/');
                            if (parts.length > 1) {
                                let rawTag = parts[1].split('?')[0].split('/')[0];
                                let cleanTag = decodeURIComponent(rawTag).replace(/%20/g, ' ');
                                if (cleanTag && cleanTag.length > 1 && cleanTag.length < 30) {
                                    discoveredTags.push(cleanTag);
                                }
                            }
                        }
                    });

                    return { links: links, tags: Array.from(new Set(discoveredTags)) };
                }''')
                
                cards_data = extracted_data["links"]
                new_tags = extracted_data["tags"]

                for n_tag in new_tags:
                    if n_tag.lower() not in tag.lower():
                        await tag_queue.put(n_tag)

                tag_communities = []
                for card in cards_data:
                    href = card["href"]
                    combined_text = card["text"] + " " + card["containerText"]
                    
                    if not href or "tumblr.com" not in href or "/tagged/" in href: continue
                    if any(x in href for x in ["/register", "/login", "/explore", "/trending", "/about", "/policy", "/dashboard", "/settings", "/privacy", "/post/"]): continue
                    if href in seen_links: continue
                    
                    url_clean = href.split('?')[0].rstrip('/')
                    parts = url_clean.replace("https://", "").replace("http://", "").split('/')
                    
                    if "communities" in parts or len(parts) == 4 or "member" in combined_text.lower():
                        member_count = parse_member_count(combined_text)
                        if member_count >= MIN_MEMBERS or "member" in combined_text.lower():
                            seen_links.add(href)
                            tag_communities.append({
                                "Tag": tag, 
                                "Community_Link": href, 
                                "Members": member_count if member_count > 0 else "Group/Blog", 
                                "Status": "Found"
                            })

                if tag_communities:
                    print(f"[{email}] Found {len(tag_communities)} new communities for tag: {tag} (Discovered new tags: {len(new_tags)})")
                    async with df_lock:
                        if os.path.exists(FILE_NAME):
                            try:
                                df_old = pd.read_excel(FILE_NAME)
                                fresh_links = set(df_old["Community_Link"].dropna().tolist())
                                seen_links.update(fresh_links)
                                filtered = [item for item in tag_communities if item["Community_Link"] not in fresh_links]
                                if filtered:
                                    df_new = pd.DataFrame(filtered)
                                    df_combined = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["Community_Link"])
                                    safe_save_excel(df_combined, FILE_NAME)
                            except Exception: pass
                        else:
                            safe_save_excel(pd.DataFrame(tag_communities), FILE_NAME)

                await page.wait_for_timeout(random.randint(2000, 4000))
            except Exception as e:
                print(f"[{email}] Error processing tag {tag}: {e}")
            tag_queue.task_done()

        try:
            await context.close()
        except: pass
        if email in ACTIVE_CONTEXTS: del ACTIVE_CONTEXTS[email]
        account_queue.task_done()

async def account_join_and_poster_worker(p, pixel_7, account_queue, link_queue, excel_file_path, df_lock, account_lock, post_link):
    while not account_queue.empty():
        if link_queue.empty(): break

        email, password = await account_queue.get()
        base_session_dir = "accounts_sessions"
        if not os.path.exists(base_session_dir): os.makedirs(base_session_dir)
        user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))

        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False, locale="en-US", timezone_id="Asia/Dhaka",
            viewport=pixel_7['viewport'], user_agent=pixel_7['user_agent'], args=STEALTH_ARGS
        )
        ACTIVE_CONTEXTS[email] = context
        page = context.pages[0] if context.pages else await context.new_page()

        if not await login_tumblr(page, email, password):
            await context.close()
            if email in ACTIVE_CONTEXTS: del ACTIVE_CONTEXTS[email]
            account_queue.task_done()
            continue

        success_joins = 0
        success_posts = 0
        attempted_links = 0

        while not link_queue.empty():
            if email not in ACTIVE_CONTEXTS: break
            if success_joins >= MAX_JOIN_PER_ACCOUNT: break

            base_url = await link_queue.get()
            attempted_links += 1
            join_url = f"{base_url}join" if base_url.endswith("/") else f"{base_url}/join"
            
            try:
                print(f"[{email}] Attempting to join: {base_url}")
                await page.goto(join_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(3500, 5000))

                mature_btn = page.locator("button:has-text('View community'), span:has-text('View community')").first
                if await mature_btn.is_visible():
                    await mature_btn.click()
                    await page.wait_for_timeout(random.randint(3000, 4500))
                    await page.goto(join_url, wait_until="domcontentloaded")

                is_joined = False

                                

                # ১. প্রথমে বাটনটির জন্য ৫ সেকেন্ড অপেক্ষা করি যাতে এটি DOM-এ চলে আসে
                agree_join_btn = page.locator("button:has-text('Agree and join'), span:has-text('Agree and join'), button:has-text('Agree and request'), button:has-text('Join')").first

                try:
                    # বাটনটি দৃশ্যমান হওয়ার জন্য সর্বোচ্চ ৫ সেকেন্ড অপেক্ষা করবে
                    await agree_join_btn.wait_for(state="visible", timeout=5000)
                    if await agree_join_btn.is_visible():
                        # force=True দিলে ওপরের কোনো লেয়ার থাকলেও জোর করে ক্লিক করবে
                        await agree_join_btn.click(force=True)
                        success_joins += 1
                        print(f"[{email}] 🎯 Progress: Joined {success_joins}/{MAX_JOIN_PER_ACCOUNT} communities.")
                        await page.wait_for_timeout(random.randint(4000, 6000))
                        is_joined = True
                except Exception as e:
                    print(f"[{email}] ⚠️ 'Agree and join' button not found via primary locator. Trying alternative...")

                # যদি প্রথমটায় কাজ না করে, তবে অল্টারনেটিভ চেক (যেমন: 'Leave' বা 'Joined' আছে কিনা)
                if not is_joined:
                    already_joined_check = page.locator("button:has-text('Leave'), button:has-text('Joined')").first
                    if await already_joined_check.is_visible():
                        success_joins += 1
                        print(f"[{email}] 🎯 Progress: Already member, counted {success_joins}/{MAX_JOIN_PER_ACCOUNT}.")
                        is_joined = True
                    else:
                        print(f"[{email}] ❌ Could not join or find membership status.")

                # পোস্ট করার অংশ
                if is_joined and post_link:
                    print(f"[{email}] Posting link to: {base_url}")
                    post_url = f"{base_url}new/link" if base_url.endswith("/") else f"{base_url}/new/link"
                    await page.goto(post_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(random.randint(4000, 6000))
                    
                    link_input = page.locator('input[placeholder*="link"], input[aria-label*="link"], .editor-link-input').first
                    if await link_input.is_visible():
                        await link_input.fill(post_link)
                        await page.wait_for_timeout(random.randint(2000, 3500))
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(random.randint(5000, 7000))
                        
                        if await handle_post_confirmation(page, email):
                            success_posts += 1
                            print(f"[{email}] Post published successfully! (Total posts: {success_posts})")
                            

                # সফলভাবে প্রসেস বা জয়েন করার পর এক্সেল ফাইল থেকে লিংক মুছে ফেলার লজিক
                if is_joined:
                    async with df_lock:
                        if os.path.exists(excel_file_path):
                            try:
                                df_current = pd.read_excel(excel_file_path)
                                df_updated = df_current[df_current["Community_Link"].str.strip() != base_url.strip()]
                                safe_save_excel(df_updated, excel_file_path)
                                print(f"    ↳ [EXCEL CLEANUP] Removed processed community link from Excel: {base_url}")
                            except Exception as ex:
                                print(f"    ↳ [EXCEL CLEANUP ERROR]: {ex}")

                await page.wait_for_timeout(random.randint(6000, 10000))
            except Exception as e:
                print(f"   ↳ [{email} ERROR]: {e}")
            
            link_queue.task_done()

        remaining_capacity = max(0, MAX_JOIN_PER_ACCOUNT - success_joins)
        
        print(f"\n===========================================================")
        print(f"📊 ACCOUNT SESSION REPORT FOR: {email}")
        print(f"   • Total Joined Communities : {success_joins}/{MAX_JOIN_PER_ACCOUNT}")
        print(f"   • Total Successful Posts   : {success_posts}")
        print(f"   • Limit Capacity Left      : {remaining_capacity} joins remaining")
        print(f"===========================================================\n")

        try:
            await context.close()
        except: pass
        if email in ACTIVE_CONTEXTS: del ACTIVE_CONTEXTS[email]
        account_queue.task_done()

# ==================== MEMBER AUDIT WORKER ====================
async def member_audit_worker(p, pixel_7, account_queue, link_queue, excel_file_path, df_lock):
    if account_queue.empty():
        return

    email, password = await account_queue.get()
    print(f"\n[LAUNCHING] Starting Audit Thread Engine via: {email}")

    base_session_dir = "accounts_sessions"
    if not os.path.exists(base_session_dir):
        os.makedirs(base_session_dir)
    user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))

    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        locale="en-US",
        timezone_id="Asia/Dhaka",
        viewport=pixel_7['viewport'],
        user_agent=pixel_7['user_agent'],
        args=STEALTH_ARGS
    )
    page = context.pages[0] if context.pages else await context.new_page()

    if not await login_tumblr(page, email, password):
        await context.close()
        account_queue.task_done()
        return

    while not link_queue.empty():
        base_url = await link_queue.get()
        print(f"[{email} ➔ Auditing]: {base_url}")

        try:
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(3000, 5000))

            mature_warning_btn = page.locator("button:has-text('View community'), span:has-text('View community')").first
            if await mature_warning_btn.is_visible():
                await mature_warning_btn.click()
                await page.wait_for_timeout(random.randint(2500, 4000))

            page_text = await page.evaluate("() => document.body.innerText")
            member_match = re.search(r'([\d\.]+[km]?)\s*member', page_text, re.IGNORECASE)

            is_valid = True
            extracted_count = "Unknown/Blog"

            if member_match:
                raw_count = member_match.group(1)
                count = parse_member_count(raw_count)
                extracted_count = count
                if count < MIN_MEMBERS:
                    is_valid = False
            else:
                if "dashboard" in page.url or "explore" in page.url:
                    is_valid = False

            async with df_lock:
                try:
                    if os.path.exists(excel_file_path):
                        df_current = pd.read_excel(excel_file_path)
                        
                        if not is_valid:
                            df_updated = df_current[df_current["Community_Link"] != base_url]
                            safe_save_excel(df_updated, excel_file_path)
                            print(f"    ↳ [AUDIT OUT] Removed: Found only {extracted_count} members.")
                        else:
                            df_current.loc[df_current["Community_Link"] == base_url, "Members"] = extracted_count
                            safe_save_excel(df_current, excel_file_path)
                            print(f"    ↳ [AUDIT PASS] Verified. Members: {extracted_count}.")
                except Exception:
                    pass

            await page.wait_for_timeout(random.randint(1500, 3000))
        except Exception as e:
            print(f"    ↳ [AUDIT ERROR] Connection failed on target URL: {e}")

        link_queue.task_done()

    await context.close()
    account_queue.task_done()

# ==================== ANIMATED START SPLASH SCREEN ====================
class SplashScreen:
    def __init__(self, root, on_complete):
        self.root = root
        self.on_complete = on_complete
        
        self.splash = tk.Toplevel(root)
        self.splash.overrideredirect(True)
        self.splash.configure(bg="#0b0e14")
        
        width, height = 550, 300
        sw = self.splash.winfo_screenwidth()
        sh = self.splash.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.splash.geometry(f"{width}x{height}+{x}+{y}")

        border_frame = tk.Frame(self.splash, bg="#3b82f6", highlightthickness=2, highlightbackground="#8b5cf6")
        border_frame.pack(fill="both", expand=True, padx=2, pady=2)

        main_box = tk.Frame(border_frame, bg="#0f172a")
        main_box.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(main_box, text="⚡ SYSTEM ACCESS GRANTED ⚡", font=("Consolas", 10, "bold"), fg="#10b981", bg="#0f172a").pack(pady=(45, 10))

        self.glow_colors = ["#3b82f6", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b", "#10b981", "#06b6d4"]
        self.color_index = 0

        self.lbl_welcome = tk.Label(
            main_box, text="Hello Alex Boss", 
            font=("Segoe UI", 28, "bold"), 
            fg=self.glow_colors[0], bg="#0f172a"
        )
        self.lbl_welcome.pack(pady=10)

        tk.Label(main_box, text="Initializing Bulk CM Bot Pro v12.2 Environment...", font=("Helvetica", 9), fg="#94a3b8", bg="#0f172a").pack(pady=(0, 20))

        self.progress_frame = tk.Frame(main_box, bg="#1e293b", height=6, width=400)
        self.progress_frame.pack(pady=10)
        self.progress_frame.pack_propagate(False)

        self.progress_bar = tk.Frame(self.progress_frame, bg="#3b82f6", height=6, width=0)
        self.progress_bar.pack(side="left", fill="y")

        self.progress_width = 0
        self.animate_glow()
        self.animate_progress()

        self.splash.after(2000, self.finish_splash)

    def animate_glow(self):
        try:
            color = self.glow_colors[self.color_index]
            self.lbl_welcome.config(fg=color)
            self.progress_bar.config(bg=color)
            self.color_index = (self.color_index + 1) % len(self.glow_colors)
            self.splash.after(150, self.animate_glow)
        except Exception:
            pass

    def animate_progress(self):
        try:
            if self.progress_width < 400:
                self.progress_width += 20
                self.progress_bar.config(width=self.progress_width)
                self.splash.after(80, self.animate_progress)
        except Exception:
            pass

    def finish_splash(self):
        try:
            self.splash.destroy()
        except Exception:
            pass
        self.on_complete()

# ==================== ANIMATED EXIT SPLASH SCREEN ====================
class ExitSplashScreen:
    def __init__(self, root):
        self.root = root
        
        self.splash = tk.Toplevel(root)
        self.splash.overrideredirect(True)
        self.splash.configure(bg="#0b0e14")
        
        width, height = 550, 300
        sw = self.splash.winfo_screenwidth()
        sh = self.splash.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.splash.geometry(f"{width}x{height}+{x}+{y}")

        border_frame = tk.Frame(self.splash, bg="#ef4444", highlightthickness=2, highlightbackground="#f59e0b")
        border_frame.pack(fill="both", expand=True, padx=2, pady=2)

        main_box = tk.Frame(border_frame, bg="#0f172a")
        main_box.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(main_box, text="⚡ SYSTEM SHUTTING DOWN ⚡", font=("Consolas", 10, "bold"), fg="#ef4444", bg="#0f172a").pack(pady=(45, 10))

        self.glow_colors = ["#ef4444", "#f59e0b", "#ec4899", "#8b5cf6", "#3b82f6", "#10b981"]
        self.color_index = 0

        self.lbl_goodbye = tk.Label(
            main_box, text="Good bye Alex Boss", 
            font=("Segoe UI", 28, "bold"), 
            fg=self.glow_colors[0], bg="#0f172a"
        )
        self.lbl_goodbye.pack(pady=10)

        tk.Label(main_box, text="Closing active sessions and saving logs...", font=("Helvetica", 9), fg="#94a3b8", bg="#0f172a").pack(pady=(0, 20))

        self.progress_frame = tk.Frame(main_box, bg="#1e293b", height=6, width=400)
        self.progress_frame.pack(pady=10)
        self.progress_frame.pack_propagate(False)

        self.progress_bar = tk.Frame(self.progress_frame, bg="#ef4444", height=6, width=400)
        self.progress_bar.pack(side="left", fill="y")

        self.progress_width = 400
        self.animate_glow()
        self.animate_progress()

        self.splash.after(2000, self.finish_exit)

    def animate_glow(self):
        try:
            color = self.glow_colors[self.color_index]
            self.lbl_goodbye.config(fg=color)
            self.progress_bar.config(bg=color)
            self.color_index = (self.color_index + 1) % len(self.glow_colors)
            self.splash.after(150, self.animate_glow)
        except Exception:
            pass

    def animate_progress(self):
        try:
            if self.progress_width > 0:
                self.progress_width -= 20
                self.progress_bar.config(width=self.progress_width)
                self.splash.after(80, self.animate_progress)
        except Exception:
            pass

    def finish_exit(self):
        try:
            self.splash.destroy()
        except Exception:
            pass
        self.root.destroy()

# ==================== MAIN UI CLASS ====================
class BulkCMBotDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Bulk CM Bot - Dashboard Overview")
        self.root.geometry("1150x700")
        self.root.configure(bg="#0b0e14")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_app)
        self.root.withdraw()

        self.BG_DARK = "#0b0e14"
        self.SIDEBAR_BG = "#12161f"
        self.BOX_BG = "#131822"
        self.TEXT_TITLE = "#58a6ff"
        self.TEXT_WHITE = "#ffffff"
        self.TEXT_MUTED = "#8b949e"
        
        self.COLOR_RED = "#da3633"
        self.COLOR_GREEN = "#238636"
        self.COLOR_YELLOW = "#d97706"
        self.COLOR_BLUE = "#3b82f6"
        self.COLOR_ORANGE = "#d97706"
        self.COLOR_PURPLE = "#8b5cf6"

        self.anim_colors = ["#3b82f6", "#8b5cf6", "#ec4899", "#ef4444", "#f59e0b", "#10b981", "#06b6d4"]
        self.anim_index = 0

        self.account_checkboxes = {}
        self.select_all_var = tk.BooleanVar(value=False)

        self.persistent_terminal_text = None
        self.terminal_logs_buffer = ""

        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure('Dark.TCheckbutton', background=self.BG_DARK, foreground="#ffffff")
        self.style.configure('Row.TCheckbutton', background=self.BOX_BG, foreground="#ffffff")

        SplashScreen(self.root, self.show_main_window)

    def on_close_app(self):
        self.root.withdraw() 
        ExitSplashScreen(self.root) 

    def show_main_window(self):
        self.setup_ui()
        self.root.deiconify()

    def setup_ui(self):
        sidebar = tk.Frame(self.root, bg=self.SIDEBAR_BG, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        logo_label = tk.Label(sidebar, text="Bulk CM Bot\nPro v12.2", font=("Helvetica", 14, "bold"), fg="#ffffff", bg=self.SIDEBAR_BG, justify="left")
        logo_label.pack(anchor="w", padx=20, pady=(25, 20))

        self.btn_dashboard = tk.Button(sidebar, text="📊 Dashboard & Filters", font=("Helvetica", 10, "bold"), fg="#ffffff", bg="#1f2937", bd=0, relief="flat", anchor="w", padx=15, command=self.show_dashboard)
        self.btn_dashboard.pack(fill="x", pady=3, padx=10)

        self.btn_terminal = tk.Button(sidebar, text="💻 Live Terminal", font=("Helvetica", 10), fg=self.TEXT_MUTED, bg=self.SIDEBAR_BG, bd=0, relief="flat", anchor="w", padx=15, command=self.show_terminal)
        self.btn_terminal.pack(fill="x", pady=3, padx=10)

        self.btn_accounts = tk.Button(sidebar, text="👤 Account Management", font=("Helvetica", 10), fg=self.TEXT_MUTED, bg=self.SIDEBAR_BG, bd=0, relief="flat", anchor="w", padx=15, command=self.show_accounts)
        self.btn_accounts.pack(fill="x", pady=3, padx=10)

        self.btn_settings = tk.Button(sidebar, text="⚙️ Settings", font=("Helvetica", 10), fg=self.TEXT_MUTED, bg=self.SIDEBAR_BG, bd=0, relief="flat", anchor="w", padx=15, command=self.show_settings)
        self.btn_settings.pack(fill="x", pady=3, padx=10)

        dev_frame = tk.Frame(sidebar, bg="#181e2a", highlightbackground="#2d3748", highlightthickness=1)
        dev_frame.pack(side="bottom", fill="x", padx=10, pady=20)

        self.lbl_dev_title = tk.Label(dev_frame, text="⚡ Developed By", font=("Consolas", 8, "bold"), fg=self.TEXT_MUTED, bg="#181e2a")
        self.lbl_dev_title.pack(pady=(6, 1))

        self.lbl_developer = tk.Label(dev_frame, text="Alex Roman", font=("Helvetica", 11, "bold"), fg="#3b82f6", bg="#181e2a")
        self.lbl_developer.pack(pady=(0, 6))

        self.animate_developer_tag()

        self.main_frame = tk.Frame(self.root, bg=self.BG_DARK)
        self.main_frame.pack(side="right", fill="both", expand=True, padx=25, pady=20)

        self.show_dashboard()

    def animate_developer_tag(self):
        try:
            current_color = self.anim_colors[self.anim_index]
            self.lbl_developer.config(fg=current_color)
            self.anim_index = (self.anim_index + 1) % len(self.anim_colors)
            self.root.after(400, self.animate_developer_tag)
        except Exception:
            pass

    def set_active_button(self, active_btn):
        for btn in [self.btn_dashboard, self.btn_terminal, self.btn_accounts, self.btn_settings]:
            btn.configure(bg=self.SIDEBAR_BG, fg=self.TEXT_MUTED, font=("Helvetica", 10))
        active_btn.configure(bg="#1f2937", fg="#ffffff", font=("Helvetica", 10, "bold"))

    def clear_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def create_stat_box(self, parent, title, value, val_color):
        box = tk.Frame(parent, bg=self.BOX_BG, highlightbackground="#2d3748", highlightthickness=1)
        box.pack(side="left", expand=True, fill="both", padx=4, pady=4)

        lbl_t = tk.Label(box, text=title, font=("Helvetica", 7, "bold"), fg=self.TEXT_MUTED, bg=self.BOX_BG)
        lbl_t.pack(pady=(12, 2))

        lbl_v = tk.Label(box, text=value, font=("Helvetica", 15, "bold"), fg=val_color, bg=self.BOX_BG)
        lbl_v.pack(pady=(0, 12))

    def show_dashboard(self):
        self.set_active_button(self.btn_dashboard)
        self.clear_main_frame()

        tk.Label(self.main_frame, text="Dashboard Overview", font=("Helvetica", 16, "bold"), fg="#ffffff", bg=self.BG_DARK).pack(anchor="w", pady=(0, 15))

        accounts = load_all_accounts("account.txt")
        total_accounts = len(accounts)

        restricted_count = sum(1 for email, _ in accounts if ACCOUNT_STATUS_MAP.get(email) == "Restricted")
        ok_count = sum(1 for email, _ in accounts if ACCOUNT_STATUS_MAP.get(email) == "No Restrictions")
        not_logged_in_count = sum(1 for email, _ in accounts if ACCOUNT_STATUS_MAP.get(email) in ["Not Logged In", None])

        total_communities = 0
        if os.path.exists(FILE_NAME):
            try:
                df = pd.read_excel(FILE_NAME)
                total_communities = len(df)
            except: pass

        threads = load_threads_count("threads_count.txt")
        promo_link, promo_image = load_post_data()
        link_status = "ACTIVE" if promo_link else "MISSING"

        sec1 = tk.LabelFrame(self.main_frame, text=" PROFILE STATUS ", font=("Helvetica", 9, "bold"), fg=self.TEXT_TITLE, bg=self.BG_DARK, bd=1, relief="solid")
        sec1.pack(fill="x", pady=(0, 15), ipady=5)
        f1 = tk.Frame(sec1, bg=self.BG_DARK)
        f1.pack(fill="x", padx=8, pady=5)

        self.create_stat_box(f1, "ALL PROFILES", str(total_accounts), self.TEXT_WHITE)
        self.create_stat_box(f1, "RESTRICTED", str(restricted_count), self.COLOR_RED)
        self.create_stat_box(f1, "NO RESTRICTIONS", str(ok_count), self.COLOR_GREEN)
        self.create_stat_box(f1, "NOT LOGGED IN", str(not_logged_in_count), self.COLOR_YELLOW)
        self.create_stat_box(f1, "UNKNOWN", "0", self.TEXT_MUTED)

        sec2 = tk.LabelFrame(self.main_frame, text=" COMMUNITY / PAGE STATUS ", font=("Helvetica", 9, "bold"), fg=self.TEXT_TITLE, bg=self.BG_DARK, bd=1, relief="solid")
        sec2.pack(fill="x", pady=(0, 15), ipady=5)
        f2 = tk.Frame(sec2, bg=self.BG_DARK)
        f2.pack(fill="x", padx=8, pady=5)

        self.create_stat_box(f2, "ALL COMMUNITIES", str(total_communities), self.TEXT_WHITE)
        self.create_stat_box(f2, "AT RISK / LOW", "0", self.COLOR_RED)
        self.create_stat_box(f2, "NO ISSUES", str(total_communities), self.COLOR_GREEN)
        self.create_stat_box(f2, "CHECKPOINT", "0", self.COLOR_YELLOW)

        sec3 = tk.LabelFrame(self.main_frame, text=" UPLOAD & THREAD STATUS ", font=("Helvetica", 9, "bold"), fg=self.TEXT_TITLE, bg=self.BG_DARK, bd=1, relief="solid")
        sec3.pack(fill="x", pady=(0, 15), ipady=5)
        f3 = tk.Frame(sec3, bg=self.BG_DARK)
        f3.pack(fill="x", padx=8, pady=5)

        self.create_stat_box(f3, "ACTIVE THREADS", str(threads), self.COLOR_BLUE)
        self.create_stat_box(f3, "PROMO LINK", link_status, self.COLOR_GREEN if promo_link else self.COLOR_RED)

        btn_refresh_dash = tk.Button(self.main_frame, text="🔄 Refresh Dashboard Stats", font=("Helvetica", 9, "bold"), bg=self.COLOR_BLUE, fg="#ffffff", bd=0, relief="flat", padx=12, pady=6, command=self.show_dashboard)
        btn_refresh_dash.pack(anchor="e", pady=(5, 0))

    def show_terminal(self):
        self.set_active_button(self.btn_terminal)
        self.clear_main_frame()
        
        tk.Label(self.main_frame, text="Live Automation Actions & Reports", font=("Helvetica", 16, "bold"), fg="#ffffff", bg=self.BG_DARK).pack(anchor="w", pady=(0, 10))

        btn_frame = tk.Frame(self.main_frame, bg=self.BG_DARK)
        btn_frame.pack(fill="x", pady=(0, 10))

        btn1 = tk.Button(btn_frame, text="▶ Run Mode 1: Finder", font=("Helvetica", 9, "bold"), bg=self.COLOR_BLUE, fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=lambda: self.run_bot_task(1))
        btn1.pack(side="left", padx=2)

        btn2 = tk.Button(btn_frame, text="▶ Run Mode 2: Join & Post", font=("Helvetica", 9, "bold"), bg=self.COLOR_GREEN, fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=lambda: self.run_bot_task(2))
        btn2.pack(side="left", padx=2)

        btn3 = tk.Button(btn_frame, text="▶ Run Mode 3: Member Checker", font=("Helvetica", 9, "bold"), bg=self.COLOR_ORANGE, fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=lambda: self.run_bot_task(3))
        btn3.pack(side="left", padx=2)
        
        btn4 = tk.Button(btn_frame, text="▶ Run Mode 4", font=("Helvetica", 9, "bold"), bg="#6366f1", fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=lambda: self.run_bot_task(4))
        btn4.pack(side="left", padx=2)

        btn_check = tk.Button(btn_frame, text="🔑 Login Check", font=("Helvetica", 9, "bold"), bg=self.COLOR_PURPLE, fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=self.run_login_check)
        btn_check.pack(side="left", padx=2)

        btn_close_all = tk.Button(btn_frame, text="✕ Close All Browsers", font=("Helvetica", 9, "bold"), bg=self.COLOR_RED, fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=self.close_all_active_browsers)
        btn_close_all.pack(side="left", padx=2)

        btn_clear = tk.Button(btn_frame, text="🧹 Clear Log", font=("Helvetica", 9, "bold"), bg="#374151", fg="#ffffff", padx=8, pady=6, bd=0, relief="flat", command=self.clear_terminal_log)
        btn_clear.pack(side="right", padx=2)

        terminal_container = tk.Frame(self.main_frame, bg="#000000", highlightbackground="#2d3748", highlightthickness=1)
        terminal_container.pack(fill="both", expand=True)

        if self.persistent_terminal_text is None or not self.persistent_terminal_text.winfo_exists():
            self.persistent_terminal_text = scrolledtext.ScrolledText(
                terminal_container, bg="#0d1117", fg="#00ff66", insertbackground="white",
                font=("Consolas", 10), wrap="word", bd=0
            )
            if self.terminal_logs_buffer:
                self.persistent_terminal_text.insert(tk.END, self.terminal_logs_buffer)
        else:
            if self.persistent_terminal_text.master != terminal_container:
                self.persistent_terminal_text.pack_forget()
                self.persistent_terminal_text.master = terminal_container

        self.persistent_terminal_text.pack(in_=terminal_container, fill="both", expand=True, padx=5, pady=5)
        self.persistent_terminal_text.see(tk.END)

        sys.stdout = RedirectText(self.persistent_terminal_text, self)
        sys.stderr = RedirectText(self.persistent_terminal_text, self)

        if not self.terminal_logs_buffer:
            print("=== Live Terminal Ready ===")

    def clear_terminal_log(self):
        self.terminal_logs_buffer = ""
        if self.persistent_terminal_text and self.persistent_terminal_text.winfo_exists():
            self.persistent_terminal_text.delete('1.0', tk.END)

    def run_login_check(self):
        self.show_terminal()

        def task_thread():
            asyncio.run(self._execute_login_check_async())

        threading.Thread(target=task_thread, daemon=True).start()
        messagebox.showinfo("Login Check Started", "Account login check process started! Check Live Terminal for results.")

    async def _execute_login_check_async(self):
        thread_count = load_threads_count("threads_count.txt")
        all_accounts = load_all_accounts("account.txt")

        if not all_accounts:
            print("[CRITICAL] account.txt is missing or empty!")
            return

        print(f"\n=================== STARTING LOGIN CHECK ===================")
        print(f"Total Accounts: {len(all_accounts)} | Parallel Threads: {thread_count}")
        print(f"===========================================================\n")

        account_queue = asyncio.Queue()
        for acc in all_accounts: 
            await account_queue.put(acc)

        async with async_playwright() as p:
            pixel_7 = p.devices['Pixel 7']
            active_threads = min(thread_count, len(all_accounts))

            workers = [login_checker_worker(p, pixel_7, account_queue) for _ in range(active_threads)]
            await asyncio.gather(*workers)

        print(f"\n=================== LOGIN CHECK COMPLETED ===================\n")

    def close_all_active_browsers(self):
        if not ACTIVE_CONTEXTS:
            messagebox.showinfo("No Active Browsers", "No running browser instances found.")
            return

        def close_thread():
            asyncio.run(self._async_close_all())

        threading.Thread(target=close_thread, daemon=True).start()

    async def _async_close_all(self):
        active_keys = list(ACTIVE_CONTEXTS.keys())
        closed_count = 0
        for email in active_keys:
            if email in ACTIVE_CONTEXTS:
                try:
                    ctx = ACTIVE_CONTEXTS[email]
                    del ACTIVE_CONTEXTS[email]
                    await ctx.close()
                    closed_count += 1
                except Exception as e:
                    print(f"Error closing browser for {email}: {e}")
        print(f"[ACTION] Closed all {closed_count} running browser instances.")
        messagebox.showinfo("Browsers Closed", f"Successfully closed {closed_count} running browser(s).")

    def show_accounts(self):
        self.set_active_button(self.btn_accounts)
        self.clear_main_frame()

        tk.Label(self.main_frame, text="Account Management", font=("Helvetica", 16, "bold"), fg="#ffffff", bg=self.BG_DARK).pack(anchor="w", pady=(0, 10))

        control_bar = tk.Frame(self.main_frame, bg=self.BG_DARK)
        control_bar.pack(fill="x", pady=(0, 10))

        self.select_all_var = tk.BooleanVar(value=False)
        chk_all = ttk.Checkbutton(
            control_bar, text="Select All", variable=self.select_all_var, 
            command=self.toggle_select_all, style='Dark.TCheckbutton'
        )
        chk_all.pack(side="left", padx=(0, 15))

        btn_run_selected = tk.Button(control_bar, text="▶ Run Selected", font=("Helvetica", 9, "bold"), bg=self.COLOR_GREEN, fg="#ffffff", bd=0, relief="flat", padx=12, pady=5, command=self.run_selected_accounts)
        btn_run_selected.pack(side="left", padx=5)

        btn_close_session = tk.Button(control_bar, text="✕ Close Session / Delete", font=("Helvetica", 9, "bold"), bg=self.COLOR_RED, fg="#ffffff", bd=0, relief="flat", padx=12, pady=5, command=self.close_selected_sessions)
        btn_close_session.pack(side="left", padx=5)

        btn_reload = tk.Button(control_bar, text="🔄 Reload List", font=("Helvetica", 9, "bold"), bg=self.COLOR_BLUE, fg="#ffffff", bd=0, relief="flat", padx=12, pady=5, command=self.show_accounts)
        btn_reload.pack(side="right", padx=5)

        list_container = tk.Frame(self.main_frame, bg=self.BOX_BG, highlightbackground="#2d3748", highlightthickness=1)
        list_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_container, bg=self.BOX_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.BOX_BG)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        accounts = load_all_accounts("account.txt")
        self.account_checkboxes = {}

        if not accounts:
            tk.Label(scrollable_frame, text="No accounts found in account.txt", font=("Helvetica", 11), fg=self.TEXT_MUTED, bg=self.BOX_BG).pack(padx=20, pady=20)
            return

        header_frame = tk.Frame(scrollable_frame, bg="#1a202c", height=30)
        header_frame.pack(fill="x", expand=True, ipady=3)
        tk.Label(header_frame, text="Select", font=("Helvetica", 9, "bold"), fg=self.TEXT_MUTED, bg="#1a202c", width=8, anchor="w").pack(side="left", padx=10)
        tk.Label(header_frame, text="Account Email", font=("Helvetica", 9, "bold"), fg=self.TEXT_MUTED, bg="#1a202c", width=35, anchor="w").pack(side="left", padx=10)
        tk.Label(header_frame, text="Status", font=("Helvetica", 9, "bold"), fg=self.TEXT_MUTED, bg="#1a202c", width=20, anchor="w").pack(side="left", padx=10)

        for acc in accounts:
            email, pwd = acc
            row = tk.Frame(scrollable_frame, bg=self.BOX_BG)
            row.pack(fill="x", expand=True, pady=2)

            var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(row, variable=var, style='Row.TCheckbutton', command=self.update_select_all_state)
            chk.pack(side="left", padx=10)

            lbl_email = tk.Label(row, text=email, font=("Helvetica", 10), fg="#ffffff", bg=self.BOX_BG, width=35, anchor="w")
            lbl_email.pack(side="left", padx=10)

            status_text = ACCOUNT_STATUS_MAP.get(email, "Not Logged In")
            status_color = self.COLOR_GREEN if status_text == "No Restrictions" else (self.COLOR_RED if status_text == "Restricted" else self.COLOR_YELLOW)

            lbl_status = tk.Label(row, text=status_text, font=("Helvetica", 9, "bold"), fg=status_color, bg=self.BOX_BG, width=20, anchor="w")
            lbl_status.pack(side="left", padx=10)

            self.account_checkboxes[acc] = var

    def toggle_select_all(self):
        new_state = self.select_all_var.get()
        for var in self.account_checkboxes.values():
            var.set(new_state)
        self.root.update_idletasks()

    def update_select_all_state(self):
        all_selected = all(var.get() for var in self.account_checkboxes.values())
        self.select_all_var.set(all_selected)
        self.root.update_idletasks()

    def run_selected_accounts(self):
        selected = [acc for acc, var in self.account_checkboxes.items() if var.get()]
        if not selected:
            messagebox.showwarning("No Selection", "Please select at least one account to run!")
            return
        
        self.show_terminal()

        def task_thread():
            asyncio.run(self._execute_async_selected(selected))

        threading.Thread(target=task_thread, daemon=True).start()
        messagebox.showinfo("Browser Opened", f"Opening Tumblr Home for {len(selected)} selected accounts...")

    def close_selected_sessions(self):
        selected = [acc for acc, var in self.account_checkboxes.items() if var.get()]
        if not selected:
            messagebox.showwarning("No Selection", "Please select accounts to close sessions!")
            return
        
        def close_thread():
            asyncio.run(self._async_close_selected(selected))

        threading.Thread(target=close_thread, daemon=True).start()

    async def _async_close_selected(self, selected):
        closed_count = 0
        for email, _ in selected:
            if email in ACTIVE_CONTEXTS:
                try:
                    ctx = ACTIVE_CONTEXTS[email]
                    del ACTIVE_CONTEXTS[email]
                    await ctx.close()
                    closed_count += 1
                except Exception as e:
                    print(f"Error closing browser for {email}: {e}")
            else:
                print(f"No active session track found for {email}")
        
        messagebox.showinfo("Browsers Closed", f"Closed {closed_count} running browser(s).")
        self.show_accounts()

    def show_settings(self):
        self.set_active_button(self.btn_settings)
        self.clear_main_frame()

        tk.Label(self.main_frame, text="⚙️ Bot Configurations & Data Editor", font=("Helvetica", 16, "bold"), fg="#ffffff", bg=self.BG_DARK).pack(anchor="w", pady=(0, 15))

        top_settings_frame = tk.LabelFrame(self.main_frame, text=" GENERAL CONFIGS ", font=("Helvetica", 9, "bold"), fg=self.TEXT_TITLE, bg=self.BG_DARK, bd=1, relief="solid")
        top_settings_frame.pack(fill="x", pady=(0, 15), ipady=5, ipadx=5)

        f_threads = tk.Frame(top_settings_frame, bg=self.BG_DARK)
        f_threads.pack(fill="x", padx=10, pady=5)
        tk.Label(f_threads, text="Threads Count (Max Parallel Browsers):", font=("Helvetica", 10), fg="#ffffff", bg=self.BG_DARK, width=32, anchor="w").pack(side="left")
        self.entry_threads = tk.Entry(f_threads, font=("Helvetica", 10), bg=self.BOX_BG, fg="#ffffff", insertbackground="white", bd=1, relief="solid", width=15)
        self.entry_threads.pack(side="left", padx=10)
        self.entry_threads.insert(0, str(load_threads_count("threads_count.txt")))

        f_promo = tk.Frame(top_settings_frame, bg=self.BG_DARK)
        f_promo.pack(fill="x", padx=10, pady=5)
        tk.Label(f_promo, text="Post/Promo Link (posts.xlsx):", font=("Helvetica", 10), fg="#ffffff", bg=self.BG_DARK, width=32, anchor="w").pack(side="left")
        self.entry_promo = tk.Entry(f_promo, font=("Helvetica", 10), bg=self.BOX_BG, fg="#ffffff", insertbackground="white", bd=1, relief="solid", width=50)
        self.entry_promo.pack(side="left", padx=10)
        self.entry_promo.insert(0, load_post_data()[0] or "")
        f_image = tk.Frame(top_settings_frame, bg=self.BG_DARK)
        f_image.pack(fill="x", padx=10, pady=5)
        tk.Label(f_image, text="Image Path (For Photo/Mode 1, 4):", font=("Helvetica", 10), fg=self.TEXT_TITLE, bg=self.BG_DARK, width=32, anchor="w").pack(side="left")
        self.entry_image_path = tk.Entry(f_image, font=("Helvetica", 10), bg=self.BOX_BG, fg="#ffffff", insertbackground="white", bd=1, relief="solid", width=50)
        self.entry_image_path.pack(side="left", padx=10)

        editor_frame = tk.LabelFrame(self.main_frame, text=" FILE EDITORS ", font=("Helvetica", 9, "bold"), fg=self.TEXT_TITLE, bg=self.BG_DARK, bd=1, relief="solid")
        editor_frame.pack(fill="both", expand=True, pady=(0, 10))

        notebook = ttk.Notebook(editor_frame)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_acc = tk.Frame(notebook, bg=self.BG_DARK)
        notebook.add(tab_acc, text=" 👤 Accounts (account.txt) ")
        self.txt_accounts = scrolledtext.ScrolledText(tab_acc, bg="#0d1117", fg="#ffffff", insertbackground="white", font=("Consolas", 10), bd=0)
        self.txt_accounts.pack(fill="both", expand=True, padx=5, pady=5)
        if os.path.exists("account.txt"):
            with open("account.txt", "r", encoding="utf-8") as f:
                self.txt_accounts.insert(tk.END, f.read())

        tab_comm = tk.Frame(notebook, bg=self.BG_DARK)
        notebook.add(tab_comm, text=" 🌐 Communities (Excel Links) ")
        self.txt_communities = scrolledtext.ScrolledText(tab_comm, bg="#0d1117", fg="#ffffff", insertbackground="white", font=("Consolas", 10), bd=0)
        self.txt_communities.pack(fill="both", expand=True, padx=5, pady=5)
        if os.path.exists(FILE_NAME):
            try:
                df = pd.read_excel(FILE_NAME)
                links = df["Community_Link"].dropna().tolist() if "Community_Link" in df.columns else []
                self.txt_communities.insert(tk.END, "\n".join(map(str, links)))
            except: pass

        tab_tags = tk.Frame(notebook, bg=self.BG_DARK)
        notebook.add(tab_tags, text=" 🏷️ Tags (tag.txt) ")
        self.txt_tags = scrolledtext.ScrolledText(tab_tags, bg="#0d1117", fg="#ffffff", insertbackground="white", font=("Consolas", 10), bd=0)
        self.txt_tags.pack(fill="both", expand=True, padx=5, pady=5)
        if os.path.exists("tag.txt"):
            with open("tag.txt", "r", encoding="utf-8") as f:
                self.txt_tags.insert(tk.END, f.read())

        btn_save_all = tk.Button(self.main_frame, text="💾 Save All Settings & Files", font=("Helvetica", 11, "bold"), bg=self.COLOR_GREEN, fg="#ffffff", bd=0, relief="flat", padx=20, pady=8, command=self.save_all_settings)
        btn_save_all.pack(anchor="e", pady=(5, 0))

    def save_all_settings(self):
        try:
            threads_val = self.entry_threads.get().strip()
            if threads_val.isdigit():
                with open("threads_count.txt", "w", encoding="utf-8") as f:
                    f.write(threads_val)

            promo_val = self.entry_promo.get().strip()
            df_promo = pd.DataFrame({"Link": [promo_val]})
            safe_save_excel(df_promo, POST_FILE_NAME)

            # ইমেজ পাথ সেভ করার কোডটি এখানে ঠিকভাবে থাকবে
            image_val = self.entry_image_path.get().strip()
            df_image = pd.DataFrame({"ImagePath": [image_val]})
            safe_save_excel(df_image, "image_config.xlsx")

            acc_val = self.txt_accounts.get("1.0", tk.END).strip()
            with open("account.txt", "w", encoding="utf-8") as f:
                f.write(acc_val)
            
            # (বাকি কোডগুলো আগের মতো নিচে থাকবে...)

            comm_val = self.txt_communities.get("1.0", tk.END).strip()
            comm_list = [line.strip() for line in comm_val.split("\n") if line.strip()]
            df_comm = pd.DataFrame({"Community_Link": comm_list, "Status": ["Found"] * len(comm_list)})
            safe_save_excel(df_comm, FILE_NAME)

            load_all_accounts("account.txt")

            messagebox.showinfo("Success", "All Settings and File Configurations have been saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def run_bot_task(self, mode):
        self.show_terminal()

        def task_thread():
            asyncio.run(self._execute_async(mode))

        threading.Thread(target=task_thread, daemon=True).start()
        messagebox.showinfo("Bot Execution Started", f"Mode {mode} started! Check Live Terminal for output.")

    async def _execute_async_selected(self, selected_accounts):
        async with async_playwright() as p:
            pixel_7 = p.devices['Pixel 7']
            workers = [open_and_hold_session(p, pixel_7, email, pwd) for email, pwd in selected_accounts]
            await asyncio.gather(*workers)

    async def _execute_async(self, mode):
        thread_count = load_threads_count("threads_count.txt")
        all_accounts = load_all_accounts("account.txt")

        if not all_accounts:
            print("[CRITICAL] account.txt is missing or empty!")
            return

        account_queue = asyncio.Queue()
        for acc in all_accounts: await account_queue.put(acc)

        async with async_playwright() as p:
            pixel_7 = p.devices['Pixel 7']
            df_lock, account_lock = asyncio.Lock(), asyncio.Lock()
            active_threads = min(thread_count, len(all_accounts))

            if mode == 1:
                initial_tags = load_initial_tags("tag.txt")
                tag_queue = asyncio.Queue()
                for t in initial_tags: await tag_queue.put(t)

                seen_links = set()
                if os.path.exists(FILE_NAME):
                    try:
                        df = pd.read_excel(FILE_NAME)
                        if "Community_Link" in df.columns: seen_links = set(df["Community_Link"].dropna().tolist())
                    except Exception: pass

                workers = [finder_worker(p, pixel_7, account_queue, tag_queue, seen_links, df_lock, account_lock) for _ in range(active_threads)]
                await asyncio.gather(*workers)

            elif mode == 2:
                post_link = load_post_data()[0]
                if not os.path.exists(FILE_NAME): return
                df = pd.read_excel(FILE_NAME)
                if "Community_Link" not in df.columns or df.empty: return

                links_to_join = df["Community_Link"].dropna().tolist()
                link_queue = asyncio.Queue()
                for raw_url in links_to_join: await link_queue.put(str(raw_url).strip())

                workers = [account_join_and_poster_worker(p, pixel_7, account_queue, link_queue, FILE_NAME, df_lock, account_lock, post_link) for _ in range(active_threads)]
                await asyncio.gather(*workers)

            elif mode == 3:
                if not os.path.exists(FILE_NAME): return
                df = pd.read_excel(FILE_NAME)
                if "Community_Link" not in df.columns or df.empty: return

                links_to_audit = df["Community_Link"].dropna().tolist()
                link_queue = asyncio.Queue()
                for raw_url in links_to_audit: await link_queue.put(str(raw_url).strip())

                workers = [member_audit_worker(p, pixel_7, account_queue, link_queue, FILE_NAME, df_lock) for _ in range(active_threads)]
                await asyncio.gather(*workers)
            elif mode == 4:
                post_link, image_path = load_post_data()
                workers = [auto_post_to_communities(p, pixel_7, account_queue, image_path, post_link, "4") for _ in range(active_threads)]
                await asyncio.gather(*workers)
                
async def auto_post_to_communities(p, device, account_queue, image_path, post_link, mode):
    account_data = await account_queue.get()
    if not account_data: 
        return
    email, password = account_data
    
    # সঠিক নিয়মে ইমেইলের @ এর আগের অংশ দিয়ে সেশন ফোল্ডার পাথ তৈরি করা
    base_session_dir = "accounts_sessions"
    if not os.path.exists(base_session_dir): 
        os.makedirs(base_session_dir)
    user_data_dir = os.path.abspath(os.path.join(base_session_dir, email.split('@')[0]))
    
    device_args = device.copy() if isinstance(device, dict) else {}
    device_args.pop("default_browser_type", None)
    
    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        accept_downloads=True,
        **device_args
    )
    page = context.pages[0] if context.pages else await context.new_page()
    print(f"\n{email} Searching for joined communities...")
    await page.goto('https://www.tumblr.com/communities', wait_until='networkidle')
    await asyncio.sleep(8)
    
    community_links = await page.eval_on_selector_all('a[href*="/communities/"]', "elements => elements.map(el => el.href)")
    unique_communities = [l.rstrip('/') for l in list(set(community_links)) if "/communities/" in l and not any(x in l for x in ["/explore", "/posts", "/all", "/tagged"])]

    total_found = len(unique_communities)
    success_count = 0
    print(f"FOUND: {total_found} COMMUNITIES\n")

    for index, url in enumerate(unique_communities, 1):
        try:
            print(f"--- Working on Community {index}/{total_found} ---")
            photo_done = False
            link_done = False

            # ১. প্রথমে ফটো পোস্ট করার অংশ
            if str(mode) in ["1", "4"]:
                try:
                    photo_url = f"{url}/new/photo"
                    await page.goto(photo_url, wait_until='domcontentloaded')
                    await asyncio.sleep(4)
                    await check_for_mature_content_warning(page, email)
                    
                    file_input = page.locator('input[type="file"]')
                    if await file_input.count() > 0 and image_path and os.path.exists(image_path):
                        await file_input.set_input_files(os.path.abspath(image_path))
                        print(" [~] Photo file selected, waiting for upload...")
                        await asyncio.sleep(8)
                        
                        await handle_post_confirmation(page, email)
                        await asyncio.sleep(4)
                        print(f" [✔] PHOTO POST SUCCESSFUL")
                        photo_done = True
                except Exception as e:
                    print(f"[!] Photo post error: {e}")

            # ২. এরপর লিংক পোস্ট করার অংশ
            if str(mode) in ["2", "3", "4"]:
                try:
                    link_url = f"{url}/new/link"
                    await page.goto(link_url, wait_until='domcontentloaded')
                    await asyncio.sleep(4)
                    await check_for_mature_content_warning(page, email)

                    if post_link and post_link != "nan":
                        link_input = page.locator('input[placeholder*="link"], input[aria-label*="link"], .editor-link-input').first
                        if await link_input.is_visible(timeout=5000):
                            await link_input.fill(post_link)
                            await asyncio.sleep(2)
                            await page.keyboard.press("Enter")
                            await asyncio.sleep(4)
                            
                            await handle_post_confirmation(page, email)
                            await asyncio.sleep(4)
                            print(f" [✔] LINK POST SUCCESSFUL")
                            link_done = True
                except Exception as e:
                    print(f"[!] Link post error: {e}")

            if photo_done or link_done:
                success_count += 1
                print(f"STATUS: {success_count}/{total_found} SUCCESSFUL POSTS\n")

            await asyncio.sleep(random.randint(5, 8))
            
        except Exception as e:
            print(f"[!] Skip {url}: {e}")
            continue

    print(f"\nFINAL REPORT FOR: {email} | Successful: {success_count}/{total_found}\n")

    # লিংক বা টেক্সট পোস্ট করার চেষ্টা
    if str(mode) in ["2", "3", "4"]:
        try:
            link_url = f"{url}/new/link"
            await page.goto(link_url, wait_until='domcontentloaded')
            await asyncio.sleep(4)
            await check_for_mature_content_warning(page, email)

            if post_link and post_link != "nan":
                link_input = page.locator('input[placeholder*="link"], input[aria-label*="link"], .editor-link-input').first
                if await link_input.is_visible(timeout=5000):
                    await link_input.fill(post_link)
                    await asyncio.sleep(2)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(6)
                    await handle_post_confirmation(page, email)
                    print(f" [✔] COMMUNITY POST SUCCESSFUL")
                    link_done = True
        except Exception as e:
            print(f"[!] Link post error: {e}")

            if photo_done or link_done:
                success_count += 1
                print(f"STATUS: {success_count}/{total_found} SUCCESSFUL POSTS")

            await asyncio.sleep(random.randint(10, 15))

        except Exception as e:
            print(f" [!] Skip {url}: {e}")
            

    print(f"\nFINAL REPORT FOR: {email} | Successful: {success_count}/{total_found}\n")                
               
async def check_for_mature_content_warning(page, email):
    try:
        # বর্তমানে আসা "View community" বাটনটি চেক করা এবং ক্লিক করা
        warning_btn = page.locator('button:has-text("View community")')
        if await warning_btn.is_visible(timeout=4000):
            await warning_btn.click()
            await asyncio.sleep(2)
    except:
        pass

async def handle_post_confirmation(page, email):
    try:
        post_btn = page.locator('button[type="submit"], button:has-text("Post")').last
        if await post_btn.is_visible(timeout=5000):
            await post_btn.click()
            await asyncio.sleep(5)
    except:
        pass               
if __name__ == "__main__":
    root = tk.Tk()
    app = BulkCMBotDashboard(root)
    root.mainloop()
