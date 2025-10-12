from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import os
from dotenv import load_dotenv
from typing import List, Dict, Any
import secrets
import asyncio

from simple_storage import SimpleUserStorage, SimpleSessionStorage
from github_client import GitHubClient
from issue_detector import IssueDetector

load_dotenv()

# Initialize services
github_client = GitHubClient()
issue_detector = IssueDetector()

app = FastAPI(
    title="OMI GitHub Issues Integration",
    description="Voice-activated GitHub issue creation via OMI",
    version="1.0.0"
)

# Store OAuth states temporarily (in production, use Redis or similar)
oauth_states = {}

# Background task to check for idle sessions
async def check_idle_sessions():
    """Background task that checks for idle recording sessions and processes them."""
    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            from simple_storage import sessions
            idle_sessions = []
            
            for session_id, session in sessions.items():
                if session.get("issue_mode") == "recording":
                    segments_count = session.get("segments_count", 0)
                    accumulated = session.get("accumulated_text", "")
                    
                    # Check idle time
                    idle_time = SimpleSessionStorage.get_session_idle_time(session_id)
                    
                    # If user silent for 5+ seconds and has at least 3 segments
                    if idle_time and idle_time > 5 and segments_count >= 3:
                        print(f"🔔 Background: Found idle session {session_id} ({idle_time:.1f}s, {segments_count} segments)", flush=True)
                        idle_sessions.append((session_id, session, accumulated, segments_count))
            
            # Process idle sessions
            for session_id, session, accumulated, segments_count in idle_sessions:
                uid = session.get("uid")
                user = SimpleUserStorage.get_user(uid)
                
                if user and user.get("access_token") and user.get("selected_repo"):
                    print(f"⏱️  Processing idle session {session_id} with {segments_count} segments...", flush=True)
                    
                    # Mark as processing
                    SimpleSessionStorage.update_session(
                        session_id,
                        issue_mode="processing"
                    )
                    
                    # Process the issue
                    try:
                        await process_issue_creation(session_id, accumulated, segments_count, user)
                    except Exception as e:
                        print(f"❌ Error processing idle session: {e}", flush=True)
                        SimpleSessionStorage.reset_session(session_id)
        
        except Exception as e:
            print(f"⚠️  Background task error: {e}", flush=True)

async def process_issue_creation(session_id: str, accumulated: str, segments_count: int, user: dict) -> str:
    """
    Process accumulated text and create GitHub issue.
    Returns status message.
    """
    # AI generates title and description from all segments
    title, description = await issue_detector.ai_generate_issue_from_segments(accumulated)
    
    # Check if AI determined this is not a valid issue
    if not title or not description:
        SimpleSessionStorage.reset_session(session_id)
        print(f"🚫 AI determined this is not a valid issue - discarding", flush=True)
        return "❌ Not a valid issue (accidental trigger)"
    
    print(f"✨ AI generated issue:", flush=True)
    print(f"   Title: '{title}'", flush=True)
    print(f"   Description: '{description[:100]}...'", flush=True)
    
    if len(title.strip()) > 3 and len(description.strip()) > 3:
        # Fetch repo labels and let AI select appropriate ones
        print(f"🏷️  Fetching repository labels...", flush=True)
        repo_labels = github_client.get_repo_labels(
            access_token=user["access_token"],
            repo_full_name=user["selected_repo"]
        )
        
        selected_labels = []
        if repo_labels:
            print(f"🏷️  Found {len(repo_labels)} labels, letting AI select...", flush=True)
            selected_labels = await issue_detector.ai_select_labels(title, description, repo_labels)
            if selected_labels:
                print(f"🏷️  AI selected labels: {', '.join(selected_labels)}", flush=True)
            else:
                print(f"🏷️  No labels selected by AI", flush=True)
        
        print(f"📤 Creating GitHub issue...", flush=True)
        
        result = await github_client.create_issue(
            access_token=user["access_token"],
            repo_full_name=user["selected_repo"],
            title=title,
            body=description,
            labels=selected_labels
        )
        
        if result and result.get("success"):
            SimpleSessionStorage.reset_session(session_id)
            issue_url = result.get('issue_url')
            issue_number = result.get('issue_number')
            print(f"🎉 SUCCESS! Issue #{issue_number}: {issue_url}", flush=True)
            return f"✅ Issue created: #{issue_number} - {title}\n{issue_url}"
        else:
            error = result.get("error", "Unknown") if result else "Failed"
            SimpleSessionStorage.reset_session(session_id)
            print(f"❌ FAILED: {error}", flush=True)
            return f"❌ Failed: {error}"
    else:
        SimpleSessionStorage.reset_session(session_id)
        print(f"⚠️  AI returned invalid issue", flush=True)
        return "❌ No valid issue content"

@app.on_event("startup")
async def startup_event():
    """Start background tasks on app startup."""
    asyncio.create_task(check_idle_sessions())
    print("🔄 Started background idle session checker", flush=True)


@app.get("/")
async def root(uid: str = Query(None)):
    """Root endpoint - Homepage with repo selection (mobile-first UI)."""
    if not uid:
        return {
            "app": "OMI GitHub Issues Integration",
            "version": "1.0.0",
            "status": "active",
            "endpoints": {
                "auth": "/auth?uid=<user_id>",
                "webhook": "/webhook?session_id=<session>&uid=<user_id>",
                "setup_check": "/setup-completed?uid=<user_id>"
            }
        }
    
    # Get user info
    user = SimpleUserStorage.get_user(uid)
    
    if not user or not user.get("access_token"):
        # Not authenticated - show auth page
        auth_url = f"/auth?uid={uid}"
        return HTMLResponse(content=f"""
        <html>
            <head>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    {get_mobile_css()}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">🐙✨</div>
                    <h1>GitHub Issues Voice Poster</h1>
                    <p>Create GitHub issues with your voice using OMI!</p>
                    
                    <a href="{auth_url}" class="btn btn-primary">🔐 Connect GitHub Account</a>
                    
                    <div class="card">
                        <h3>📱 How to Use</h3>
                        <ol>
                            <li>Connect your GitHub account</li>
                            <li>Select which repository to create issues in</li>
                            <li>Say <strong>"Feedback Post"</strong> to your OMI</li>
                            <li>Describe your problem in detail</li>
                            <li>AI creates a properly formatted issue!</li>
                        </ol>
                    </div>
                    
                    <div class="card">
                        <h3>💬 Example</h3>
                        <div class="example">
                            "Feedback Post, the app keeps crashing when I try to upload photos. 
                            It happens every time on my iPhone. The app freezes for a second and 
                            then closes completely. This started after the latest update."
                        </div>
                    </div>
                </div>
            </body>
        </html>
        """)
    
    # Authenticated - show repo selection page
    repos = user.get("available_repos", [])
    selected_repo = user.get("selected_repo", "")
    github_username = user.get("github_username", "Unknown")
    
    repo_options = ""
    for repo in repos:
        selected_attr = 'selected' if repo['full_name'] == selected_repo else ''
        privacy = "🔒" if repo.get('private') else "🌐"
        repo_options += f'<option value="{repo["full_name"]}" {selected_attr}>{privacy} {repo["full_name"]}</option>'
    
    return HTMLResponse(content=f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>GitHub Issues - Settings</title>
            <style>
                {get_mobile_css()}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-success">
                    <div class="icon">✅</div>
                    <h1>Connected to GitHub</h1>
                    <p class="username">@{github_username}</p>
                </div>
                
                <div class="card">
                    <h2>📋 Issue Repository</h2>
                    <p>Select where voice feedback issues should be created:</p>
                    
                    <select id="repoSelect" class="repo-select">
                        {repo_options if repo_options else '<option>No repositories found</option>'}
                    </select>
                    
                    <button class="btn btn-primary" onclick="updateRepo()">💾 Save Repository</button>
                    <button class="btn btn-secondary" onclick="refreshRepos()">🔄 Refresh Repos</button>
                </div>
                
                <div class="card">
                    <h3>🎤 How to Create Issues</h3>
                    <div class="steps">
                        <div class="step">
                            <div class="step-number">1</div>
                            <div class="step-content">
                                Say <strong>"Feedback Post"</strong> to your OMI device
                            </div>
                        </div>
                        <div class="step">
                            <div class="step-number">2</div>
                            <div class="step-content">
                                Describe your problem in detail (speak naturally for 15-20 seconds)
                            </div>
                        </div>
                        <div class="step">
                            <div class="step-number">3</div>
                            <div class="step-content">
                                AI processes your speech and creates a formatted issue
                            </div>
                        </div>
                        <div class="step">
                            <div class="step-number">4</div>
                            <div class="step-content">
                                Get notification with issue link!
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h3>💡 Tips</h3>
                    <ul>
                        <li>Speak clearly and describe the problem in detail</li>
                        <li>Mention what you were doing when it happened</li>
                        <li>Include device/browser info if relevant</li>
                        <li>The AI will format everything nicely for you!</li>
                    </ul>
                </div>
                
                <div class="card">
                    <a href="/test?uid={uid}" class="btn btn-secondary btn-block">🧪 Test Interface</a>
                </div>
            </div>
            
            <script>
                async function updateRepo() {{
                    const select = document.getElementById('repoSelect');
                    const repo = select.value;
                    
                    if (!repo || repo === 'No repositories found') {{
                        alert('Please select a valid repository');
                        return;
                    }}
                    
                    try {{
                        const response = await fetch('/update-repo?uid={uid}&repo=' + encodeURIComponent(repo), {{
                            method: 'POST'
                        }});
                        
                        const data = await response.json();
                        
                        if (data.success) {{
                            alert('✅ Repository updated successfully!');
                        }} else {{
                            alert('❌ Failed to update: ' + data.error);
                        }}
                    }} catch (error) {{
                        alert('❌ Error: ' + error.message);
                    }}
                }}
                
                async function refreshRepos() {{
                    if (!confirm('Refresh your repository list from GitHub?')) return;
                    
                    try {{
                        const response = await fetch('/refresh-repos?uid={uid}', {{
                            method: 'POST'
                        }});
                        
                        const data = await response.json();
                        
                        if (data.success) {{
                            alert('✅ Repositories refreshed! Reloading page...');
                            window.location.reload();
                        }} else {{
                            alert('❌ Failed to refresh: ' + data.error);
                        }}
                    }} catch (error) {{
                        alert('❌ Error: ' + error.message);
                    }}
                }}
            </script>
        </body>
    </html>
    """)


@app.get("/auth")
async def auth_start(uid: str = Query(..., description="User ID from OMI")):
    """Start OAuth flow for GitHub authentication."""
    redirect_uri = os.getenv("OAUTH_REDIRECT_URL", "http://localhost:8000/auth/callback")
    
    try:
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        oauth_states[state] = uid
        
        # Get authorization URL
        auth_url = github_client.get_authorization_url(redirect_uri, state)
        
        return RedirectResponse(url=auth_url)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OAuth initialization failed: {str(e)}")


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None)
):
    """Handle OAuth callback from GitHub."""
    if not code or not state:
        return HTMLResponse(
            content="""
            <html>
                <body style="font-family: Arial; padding: 40px; text-align: center;">
                    <h2>❌ Authentication Failed</h2>
                    <p>Authorization code not received. Please try again.</p>
                </body>
            </html>
            """,
            status_code=400
        )
    
    # Verify state and get uid
    uid = oauth_states.get(state)
    if not uid:
        return HTMLResponse(
            content="""
            <html>
                <body style="font-family: Arial; padding: 40px; text-align: center;">
                    <h2>❌ Invalid State</h2>
                    <p>OAuth state mismatch. Please try again.</p>
                </body>
            </html>
            """,
            status_code=400
        )
    
    try:
        # Exchange code for access token
        token_data = github_client.exchange_code_for_token(code)
        access_token = token_data.get("access_token")
        
        # Get user info
        user_info = github_client.get_user_info(access_token)
        github_username = user_info.get("login", "Unknown")
        
        # Get user's repositories
        repos = github_client.list_user_repos(access_token)
        
        # Save user data
        SimpleUserStorage.save_user(
            uid=uid,
            access_token=access_token,
            github_username=github_username,
            selected_repo=repos[0]["full_name"] if repos else None,
            available_repos=repos
        )
        
        # Clean up state
        if state in oauth_states:
            del oauth_states[state]
        
        return HTMLResponse(
            content=f"""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        {get_mobile_css()}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success-box">
                            <div class="icon">✅</div>
                            <h2>Successfully Connected!</h2>
                            <p>Your GitHub account <strong>@{github_username}</strong> is now linked to OMI.</p>
                            <p>Found <strong>{len(repos)}</strong> repositories.</p>
                        </div>
                        
                        <a href="/?uid={uid}" class="btn btn-primary btn-block">Go to Settings →</a>
                        
                        <div class="card">
                            <p style="text-align: center; color: #666;">
                                You can now create issues by saying<br>
                                <strong>"Feedback Post"</strong> to your OMI device!
                            </p>
                        </div>
                    </div>
                </body>
            </html>
            """
        )
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(
            content=f"""
            <html>
                <body style="font-family: Arial; padding: 40px; text-align: center;">
                    <h2>❌ Authentication Error</h2>
                    <p>Failed to complete authentication: {str(e)}</p>
                    <p><a href="/auth?uid={uid}">Try again</a></p>
                </body>
            </html>
            """,
            status_code=500
        )


@app.get("/setup-completed")
async def check_setup(uid: str = Query(..., description="User ID from OMI")):
    """Check if user has completed setup (authenticated with GitHub)."""
    is_authenticated = SimpleUserStorage.is_authenticated(uid)
    has_repo = SimpleUserStorage.has_selected_repo(uid)
    
    return {
        "is_setup_completed": is_authenticated and has_repo
    }


@app.post("/update-repo")
async def update_repo(
    uid: str = Query(...),
    repo: str = Query(...)
):
    """Update user's selected repository."""
    try:
        success = SimpleUserStorage.update_repo_selection(uid, repo)
        if success:
            return {"success": True, "message": f"Repository updated to {repo}"}
        else:
            return {"success": False, "error": "User not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/refresh-repos")
async def refresh_repos(uid: str = Query(...)):
    """Refresh user's repository list from GitHub."""
    try:
        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return {"success": False, "error": "User not authenticated"}
        
        # Fetch fresh repo list
        repos = github_client.list_user_repos(user["access_token"])
        
        # Update storage
        SimpleUserStorage.save_user(
            uid=uid,
            access_token=user["access_token"],
            github_username=user.get("github_username"),
            selected_repo=user.get("selected_repo"),
            available_repos=repos
        )
        
        return {"success": True, "repos_count": len(repos)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/webhook")
async def webhook(
    request: Request,
    uid: str = Query(..., description="User ID from OMI"),
    session_id: str = Query(None, description="Session ID from OMI (optional)")
):
    """
    Real-time transcript webhook endpoint.
    Collects 5 segments for detailed issue description.
    """
    # Use consistent session_id per user
    if not session_id:
        session_id = f"omi_session_{uid}"
    
    # Get user
    user = SimpleUserStorage.get_user(uid)
    
    if not user or not user.get("access_token"):
        return JSONResponse(
            content={
                "message": "User not authenticated. Please complete setup first.",
                "setup_required": True
            },
            status_code=401
        )
    
    if not user.get("selected_repo"):
        return JSONResponse(
            content={
                "message": "No repository selected. Please select a repository in settings.",
                "setup_required": True
            },
            status_code=400
        )
    
    # Parse payload from OMI
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")
    
    # Handle both formats
    segments = []
    if isinstance(payload, dict):
        segments = payload.get("segments", [])
        if not session_id and "session_id" in payload:
            session_id = payload["session_id"]
    elif isinstance(payload, list):
        segments = payload
    
    # Log received data
    print(f"📥 Received {len(segments) if segments else 0} segment(s) from OMI", flush=True)
    if segments:
        for i, seg in enumerate(segments[:3]):
            text = seg.get('text', 'NO TEXT') if isinstance(seg, dict) else str(seg)
            print(f"   Segment {i}: {text[:100]}", flush=True)
    
    if not segments or not isinstance(segments, list):
        return {"status": "ok"}
    
    # Ensure consistent session_id
    if not session_id:
        session_id = f"omi_session_{uid}"
    
    # Get or create session
    session = SimpleSessionStorage.get_or_create_session(session_id, uid)
    
    # Debug session state
    print(f"📊 Session state: mode={session.get('issue_mode')}, count={session.get('segments_count', 0)}", flush=True)
    
    # Process segments
    response_message = await process_segments(session, segments, user)
    
    # Only send notifications for final issue creation
    if response_message and ("✅ Issue created:" in response_message or "❌ Failed:" in response_message):
        print(f"✉️  USER NOTIFICATION: {response_message}", flush=True)
        return {
            "message": response_message,
            "session_id": session_id,
            "processed_segments": len(segments)
        }
    
    # Silent response during collection
    print(f"🔇 Silent response: {response_message}", flush=True)
    return {"status": "ok"}


async def process_segments(
    session: dict,
    segments: List[Dict[str, Any]],
    user: dict
) -> str:
    """
    Collect exactly 5 segments after 'Feedback Post', then AI generates issue.
    - Segment 1: Contains "Feedback Post" + start of description
    - Segments 2-5: Continued detailed description
    - AI generates title and description
    
    For test interface: processes the entire text immediately as all 5 segments.
    """
    # Extract text from segments
    segment_texts = [seg.get("text", "") for seg in segments]
    full_text = " ".join(segment_texts)
    
    session_id = session["session_id"]
    is_test_session = session_id.startswith("test_session")
    
    print(f"🔍 Received: '{full_text}'", flush=True)
    print(f"📊 Session mode: {session['issue_mode']}, Count: {session.get('segments_count', 0)}/5", flush=True)
    
    # Check for trigger phrase (but only if not already recording)
    if issue_detector.detect_trigger(full_text) and session["issue_mode"] == "idle":
        issue_content = issue_detector.extract_issue_content(full_text)
        
        print(f"🎤 TRIGGER! {'[TEST MODE] Processing immediately...' if is_test_session else 'Starting segment collection...'}", flush=True)
        print(f"   Content: '{issue_content}'", flush=True)
        
        # TEST MODE: Process entire text immediately
        if is_test_session and len(issue_content) > 20:
            print(f"🧪 Test mode: Processing full text as all 5 segments...", flush=True)
            
            # AI generates title and description from full text
            title, description = await issue_detector.ai_generate_issue_from_segments(issue_content)
            
            # Check if AI determined this is not a valid issue
            if not title or not description:
                SimpleSessionStorage.reset_session(session_id)
                print(f"🚫 AI determined this is not a valid issue - discarding", flush=True)
                return "❌ Not a valid issue (accidental trigger)"
            
            print(f"✨ AI generated issue:", flush=True)
            print(f"   Title: '{title}'", flush=True)
            print(f"   Description: '{description[:100]}...'", flush=True)
            
            if len(title.strip()) > 3 and len(description.strip()) > 3:
                # Fetch repo labels and let AI select appropriate ones
                print(f"🏷️  Fetching repository labels...", flush=True)
                repo_labels = github_client.get_repo_labels(
                    access_token=user["access_token"],
                    repo_full_name=user["selected_repo"]
                )
                
                selected_labels = []
                if repo_labels:
                    print(f"🏷️  Found {len(repo_labels)} labels, letting AI select...", flush=True)
                    selected_labels = await issue_detector.ai_select_labels(title, description, repo_labels)
                    if selected_labels:
                        print(f"🏷️  AI selected labels: {', '.join(selected_labels)}", flush=True)
                    else:
                        print(f"🏷️  No labels selected by AI", flush=True)
                
                print(f"📤 Creating GitHub issue...", flush=True)
                
                result = await github_client.create_issue(
                    access_token=user["access_token"],
                    repo_full_name=user["selected_repo"],
                    title=title,
                    body=description,
                    labels=selected_labels
                )
                
                if result and result.get("success"):
                    SimpleSessionStorage.reset_session(session_id)
                    issue_url = result.get('issue_url')
                    issue_number = result.get('issue_number')
                    print(f"🎉 SUCCESS! Issue #{issue_number}: {issue_url}", flush=True)
                    return f"✅ Issue created: #{issue_number} - {title}\n{issue_url}"
                else:
                    error = result.get("error", "Unknown") if result else "Failed"
                    SimpleSessionStorage.reset_session(session_id)
                    print(f"❌ FAILED: {error}", flush=True)
                    return f"❌ Failed: {error}"
            else:
                SimpleSessionStorage.reset_session(session_id)
                print(f"⚠️  AI returned invalid issue", flush=True)
                return "❌ No valid issue content"
        
        # REAL MODE: Start collecting segments (for actual OMI device)
        SimpleSessionStorage.update_session(
            session_id,
            issue_mode="recording",
            accumulated_text=issue_content or full_text,
            segments_count=1
        )
        
        return "collecting_1"
    
    # If in recording mode, collect more segments (intelligent dynamic collection)
    elif session["issue_mode"] == "recording":
        accumulated = session.get("accumulated_text", "")
        segments_count = session.get("segments_count", 0)
        
        # Constants
        MIN_SEGMENTS = 3  # Minimum for quality (trigger + 2 more)
        GOOD_SEGMENTS = 5  # Ideal amount for context
        MAX_SEGMENTS = 10  # Safety limit
        IDLE_TIMEOUT = 5  # Process after 5s of silence
        
        # Check idle time to detect silence
        idle_time = SimpleSessionStorage.get_session_idle_time(session_id)
        
        # If user went silent for 5+ seconds, process what we have
        if idle_time and idle_time > IDLE_TIMEOUT and segments_count >= MIN_SEGMENTS:
            print(f"⏱️  User silent for {idle_time:.1f}s, processing with {segments_count} segments...", flush=True)
            # Don't add new segment, process what we had
            should_process = True
        else:
            # Add this new segment
            accumulated += " " + full_text
            segments_count += 1
            
            print(f"📝 Segment {segments_count}: '{full_text}'", flush=True)
            print(f"📚 Full accumulated: '{accumulated[:150]}...'", flush=True)
            
            # Update session with new segment
            SimpleSessionStorage.update_session(
                session_id,
                accumulated_text=accumulated,
                segments_count=segments_count
            )
            
            # Collect at least 3 segments minimum before any processing
            if segments_count < MIN_SEGMENTS:
                print(f"⏳ Collecting minimum segments ({segments_count}/{MIN_SEGMENTS})...", flush=True)
                return f"collecting_{segments_count}"
            
            # Collect up to 5 segments without AI check (good quality baseline)
            if segments_count < GOOD_SEGMENTS:
                print(f"⏳ Collecting segments ({segments_count}/{GOOD_SEGMENTS} for quality)...", flush=True)
                return f"collecting_{segments_count}"
            
            # After 5 segments, check if we need more or should process
            should_process = False
            
            # Check if we hit max segments (safety limit)
            if segments_count >= MAX_SEGMENTS:
                print(f"⚠️  Reached max segments ({MAX_SEGMENTS}), processing now...", flush=True)
                should_process = True
            else:
                # Ask AI if we have enough and if user is still on topic
                print(f"🤖 Checking with AI if issue is complete...", flush=True)
                check_result = await issue_detector.ai_check_if_issue_complete(accumulated, segments_count)
                
                is_complete = check_result.get("is_complete", False)
                is_on_topic = check_result.get("is_still_on_topic", True)
                reason = check_result.get("reason", "")
                
                print(f"🤖 AI Check: complete={is_complete}, on_topic={is_on_topic}, reason='{reason}'", flush=True)
                
                # Decision logic - BE VERY LENIENT
                if is_complete:
                    # AI says we have enough - process it!
                    print(f"✅ AI says we have enough! Processing now...", flush=True)
                    should_process = True
                elif not is_on_topic and len(accumulated.strip()) < 15:
                    # User went completely off-topic with almost no content - likely accidental
                    print(f"🚫 Off-topic with no content (<15 chars), discarding...", flush=True)
                    SimpleSessionStorage.reset_session(session_id)
                    return "discarded"
                elif not is_on_topic:
                    # User went off-topic but we have content - process what we have!
                    print(f"✅ User went off-topic but have content, processing...", flush=True)
                    should_process = True
                else:
                    # Not complete yet, but still on topic - keep collecting
                    print(f"⏳ Need more details, continuing collection...", flush=True)
                    return f"collecting_{segments_count}"
        
        # If not ready to process, return early
        if not should_process:
            return f"collecting_{segments_count}"
        
        # Mark as processing to prevent duplicates
        SimpleSessionStorage.update_session(
            session_id,
            issue_mode="processing",
            accumulated_text=accumulated,
            segments_count=segments_count
        )
        
        # Process the issue using helper function
        print(f"✅ Processing issue with {segments_count} segments...", flush=True)
        return await process_issue_creation(session_id, accumulated, segments_count, user)
    
    # If already processing, ignore additional segments
    elif session["issue_mode"] == "processing":
        print(f"⏳ Already processing issue, ignoring this segment", flush=True)
        return "processing"
    
    # Passive listening
    return "listening"


@app.get("/test")
async def test_interface(uid: str = Query("test_user_123")):
    """Web interface for testing issue creation."""
    return HTMLResponse(content=f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>GitHub Issues - Test Interface</title>
            <style>
                {get_mobile_css()}
                .log {{
                    background: #f7f9fa;
                    border: 1px solid #e1e8ed;
                    border-radius: 8px;
                    padding: 15px;
                    max-height: 300px;
                    overflow-y: auto;
                    font-family: 'Monaco', 'Courier New', monospace;
                    font-size: 13px;
                    margin-top: 15px;
                }}
                .log-entry {{
                    padding: 5px 0;
                    border-bottom: 1px solid #e1e8ed;
                }}
                .timestamp {{
                    color: #657786;
                    margin-right: 10px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-success">
                    <h1>🧪 Test Interface</h1>
                    <p>Test GitHub issue creation without OMI device</p>
                </div>

                <div class="card">
                    <h2>Authentication</h2>
                    <div class="input-group">
                        <label>User ID (UID):</label>
                        <input type="text" id="uid" value="{uid}">
                    </div>
                    <button class="btn btn-primary" onclick="authenticate()">🔐 Authenticate GitHub</button>
                    <button class="btn btn-secondary" onclick="checkAuth()">🔍 Check Auth Status</button>
                    <div id="authStatus" style="margin-top: 10px;"></div>
                </div>

                <div class="card">
                    <h2>Test Voice Commands</h2>
                    <div class="input-group">
                        <label>What would you say to OMI:</label>
                        <textarea id="voiceInput" rows="5" placeholder='Example: "Feedback Post, the app keeps crashing when I try to upload photos. It happens every time on my iPhone 14. The app freezes for a second and then closes completely. This started after the latest update and makes the app unusable."'></textarea>
                    </div>
                    <button class="btn btn-primary" onclick="sendCommand()">🎤 Send Command</button>
                    <button class="btn btn-secondary" onclick="clearLogs()">🗑️ Clear Logs</button>
                    
                    <div id="status" class="status"></div>
                </div>

                <div class="card">
                    <h3>Quick Examples (Click to use)</h3>
                    <div class="example" onclick="useExample(this)">
                        Feedback Post, the app keeps crashing when I try to upload photos. It happens every time on my iPhone 14. The app freezes and then closes. This started after the latest update.
                    </div>
                    <div class="example" onclick="useExample(this)">
                        Feedback Post, I found a bug where the search function doesn't work properly. When I type in the search bar nothing happens. I've tried on both Chrome and Safari. It worked fine last week.
                    </div>
                    <div class="example" onclick="useExample(this)">
                        Create issue, the dark mode toggle is not saving my preference. Every time I reopen the app it goes back to light mode. This is really annoying because I prefer dark mode.
                    </div>
                </div>

                <div class="card">
                    <h2>Activity Log</h2>
                    <div id="log" class="log">
                        <div class="log-entry">
                            <span class="timestamp">Ready</span>
                            <span>Waiting for commands...</span>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                const sessionId = 'test_session_' + Date.now();
                
                function addLog(message) {{
                    const log = document.getElementById('log');
                    const entry = document.createElement('div');
                    entry.className = 'log-entry';
                    const time = new Date().toLocaleTimeString();
                    entry.innerHTML = `<span class="timestamp">[${{time}}]</span><span>${{message}}</span>`;
                    log.insertBefore(entry, log.firstChild);
                }}
                
                function setStatus(message, type = 'info') {{
                    const status = document.getElementById('status');
                    status.textContent = message;
                    status.className = 'status ' + type;
                    status.style.display = 'block';
                }}
                
                async function checkAuth() {{
                    const uid = document.getElementById('uid').value;
                    try {{
                        const response = await fetch(`/setup-completed?uid=${{uid}}`);
                        const data = await response.json();
                        
                        const authStatus = document.getElementById('authStatus');
                        if (data.is_setup_completed) {{
                            authStatus.innerHTML = '<div class="success-box">✅ Connected to GitHub with repository selected</div>';
                            addLog('✅ Authentication verified');
                        }} else {{
                            authStatus.innerHTML = '<div class="error-box">❌ Not connected or no repository selected</div>';
                            addLog('❌ Not authenticated');
                        }}
                    }} catch (error) {{
                        addLog('❌ Error: ' + error.message);
                    }}
                }}
                
                function authenticate() {{
                    const uid = document.getElementById('uid').value;
                    addLog('Opening GitHub authentication...');
                    window.open(`/auth?uid=${{uid}}`, '_blank');
                    setTimeout(() => addLog('After authenticating, click "Check Auth Status"'), 1000);
                }}
                
                async function sendCommand() {{
                    const uid = document.getElementById('uid').value;
                    const voiceInput = document.getElementById('voiceInput').value;
                    
                    if (!uid || !voiceInput) {{
                        alert('Please enter both User ID and voice command');
                        return;
                    }}
                    
                    setStatus('🎤 Processing command...', 'recording');
                    addLog('📤 Sending: "' + voiceInput.substring(0, 100) + '..."');
                    
                    try {{
                        const segments = [{{
                            text: voiceInput,
                            speaker: "SPEAKER_00",
                            speakerId: 0,
                            is_user: true,
                            start: 0.0,
                            end: 5.0
                        }}];
                        
                        const response = await fetch(`/webhook?session_id=${{sessionId}}&uid=${{uid}}`, {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(segments)
                        }});
                        
                        const data = await response.json();
                        
                        if (response.ok) {{
                            if (data.message && data.message.includes('✅')) {{
                                setStatus(data.message, 'success');
                                addLog('✅ ' + data.message);
                            }} else if (data.message && data.message.includes('❌')) {{
                                setStatus(data.message, 'error');
                                addLog('❌ ' + data.message);
                            }} else {{
                                setStatus('Collecting feedback... (send more segments)', 'recording');
                                addLog('📝 ' + (data.message || 'Processing...'));
                            }}
                        }} else {{
                            setStatus('❌ Error: ' + (data.message || 'Unknown error'), 'error');
                            addLog('❌ Error: ' + (data.message || 'Unknown error'));
                        }}
                    }} catch (error) {{
                        setStatus('❌ Network error', 'error');
                        addLog('❌ Network error: ' + error.message);
                    }}
                }}
                
                function useExample(element) {{
                    document.getElementById('voiceInput').value = element.textContent.trim();
                    addLog('📝 Example loaded');
                }}
                
                function clearLogs() {{
                    document.getElementById('log').innerHTML = '<div class="log-entry"><span class="timestamp">Cleared</span><span>Logs cleared</span></div>';
                    setStatus('');
                }}
                
                window.onload = () => checkAuth();
            </script>
        </body>
    </html>
    """)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "omi-github-issues"}


def get_mobile_css() -> str:
    """Returns mobile-first CSS styles."""
    return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #24292e 0%, #1a1e22 100%);
            min-height: 100vh;
            padding: 20px;
            line-height: 1.6;
        }
        
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        
        .icon {
            font-size: 48px;
            text-align: center;
            margin-bottom: 15px;
        }
        
        h1 {
            color: white;
            font-size: 28px;
            text-align: center;
            margin-bottom: 10px;
        }
        
        h2 {
            color: #24292e;
            font-size: 22px;
            margin-bottom: 15px;
        }
        
        h3 {
            color: #24292e;
            font-size: 18px;
            margin-bottom: 10px;
        }
        
        p {
            color: white;
            text-align: center;
            margin-bottom: 20px;
        }
        
        .username {
            color: #58a6ff;
            font-weight: 600;
        }
        
        .header-success {
            background: linear-gradient(135deg, #2ea44f 0%, #238636 100%);
            padding: 30px 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        
        .btn {
            display: inline-block;
            padding: 12px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            margin: 5px 5px 5px 0;
        }
        
        .btn-primary {
            background: #2ea44f;
            color: white;
        }
        
        .btn-primary:hover {
            background: #2c974b;
        }
        
        .btn-secondary {
            background: #6e7681;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #57606a;
        }
        
        .btn-block {
            display: block;
            width: 100%;
            text-align: center;
        }
        
        .repo-select {
            width: 100%;
            padding: 12px;
            border: 2px solid #d0d7de;
            border-radius: 6px;
            font-size: 14px;
            margin-bottom: 15px;
            font-family: inherit;
        }
        
        input[type="text"], textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #d0d7de;
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
        }
        
        textarea {
            resize: vertical;
            min-height: 80px;
        }
        
        .input-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #24292e;
            font-size: 14px;
        }
        
        .example {
            background: #f6f8fa;
            padding: 12px;
            border-radius: 6px;
            margin: 8px 0;
            font-size: 13px;
            cursor: pointer;
            border: 2px solid transparent;
            color: #24292e;
        }
        
        .example:hover {
            border-color: #2ea44f;
            background: #e8f5e9;
        }
        
        .steps {
            margin: 15px 0;
        }
        
        .step {
            display: flex;
            margin: 15px 0;
            align-items: flex-start;
        }
        
        .step-number {
            background: #2ea44f;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            margin-right: 12px;
            flex-shrink: 0;
        }
        
        .step-content {
            flex: 1;
            padding-top: 5px;
        }
        
        .success-box {
            background: #d4edda;
            color: #155724;
            padding: 20px;
            border-radius: 8px;
            margin: 15px 0;
            text-align: center;
        }
        
        .error-box {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
        }
        
        .status {
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            font-weight: 500;
            display: none;
        }
        
        .status.info {
            background: #e8f5fe;
            color: #0969da;
        }
        
        .status.recording {
            background: #fff3cd;
            color: #856404;
        }
        
        .status.success {
            background: #d4edda;
            color: #155724;
        }
        
        .status.error {
            background: #f8d7da;
            color: #721c24;
        }
        
        ul, ol {
            margin-left: 20px;
        }
        
        li {
            margin: 8px 0;
        }
        
        strong {
            color: #2ea44f;
        }
        
        @media (max-width: 480px) {
            body {
                padding: 10px;
            }
            
            .card {
                padding: 15px;
            }
            
            h1 {
                font-size: 24px;
            }
            
            .btn {
                display: block;
                width: 100%;
                margin: 8px 0;
            }
        }
    """


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    host = os.getenv("APP_HOST", "0.0.0.0")
    
    print("🐙 OMI GitHub Issues Integration")
    print("=" * 50)
    print("✅ Using file-based storage")
    print(f"🚀 Starting on {host}:{port}")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True
    )

