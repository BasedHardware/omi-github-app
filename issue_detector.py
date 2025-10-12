import re
from typing import Optional, Tuple
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class IssueDetector:
    """Detects issue creation commands and extracts issue content intelligently."""
    
    TRIGGER_PHRASES = [
        # Feedback variations
        "feedback post",
        "post feedback",
        "submit feedback",
        "send feedback",
        "give feedback",
        "product feedback",
        "app feedback",
        
        # Issue variations
        "create issue",
        "create an issue",
        "report issue",
        "report an issue",
        "file issue",
        "file an issue",
        "new issue",
        "open issue",
        "post issue",
        "submit issue",
        "log issue",
        
        # Bug variations
        "report bug",
        "report a bug",
        "create bug",
        "file bug",
        "post bug",
        "bug report",
        "found a bug",
        "found bug",
        
        # GitHub specific
        "github issue",
        "github post",
        "github bug",
        
        # General reporting
        "create ticket",
        "file ticket",
        "report problem",
        "problem report"
    ]
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for comparison."""
        return text.lower().strip()
    
    @classmethod
    def detect_trigger(cls, text: str) -> bool:
        """Check if text contains an issue trigger phrase."""
        normalized = cls.normalize_text(text)
        return any(trigger in normalized for trigger in cls.TRIGGER_PHRASES)
    
    @classmethod
    def extract_issue_content(cls, text: str) -> Optional[str]:
        """Extract issue content after trigger phrase."""
        normalized = cls.normalize_text(text)
        
        # Find the trigger phrase
        trigger_index = -1
        matched_trigger = None
        for trigger in cls.TRIGGER_PHRASES:
            idx = normalized.find(trigger)
            if idx != -1:
                trigger_index = idx
                matched_trigger = trigger
                break
        
        if trigger_index == -1:
            return None
        
        # Extract content after trigger
        start_index = trigger_index + len(matched_trigger)
        content = text[start_index:].strip()
        
        return content if content else None
    
    @classmethod
    async def ai_check_if_issue_complete(cls, accumulated_text: str, segment_count: int) -> dict:
        """
        Check if the accumulated text is sufficient to create an issue.
        Returns dict with:
        - is_complete: bool (True if we have enough to create an issue)
        - is_still_on_topic: bool (True if user is still describing the issue)
        - reason: str (explanation)
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are analyzing voice transcripts to determine if we have enough information to create a GitHub issue.

Analyze the accumulated speech and answer TWO questions:

1. **Is this enough to create an issue?**
   - YES if: ANYTHING that could be a problem, feature, or feedback
   - YES if: Even a hint of an issue or idea
   - NO ONLY if: Complete gibberish like "test test test" or "check check check"
   - BE VERY LENIENT: Almost ALWAYS say YES unless impossible to understand
   
2. **Is the user still talking about the same issue?**
   - YES if: Could possibly be related to the topic
   - YES if: Continuing any thought about software/apps
   - NO ONLY if: Clearly personal conversation (dinner, groceries, weather)
   - BE VERY LENIENT: Almost ALWAYS say YES unless obviously unrelated

Respond in this EXACT format:
COMPLETE: yes/no
ON_TOPIC: yes/no
REASON: brief explanation

Examples:

Input (2 segments): "the app crashes when I upload photos"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: Clear crash issue

Input (2 segments): "create a ride hailing app for Uber"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: Clear feature request

Input (2 segments): "app for rides"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: Feature idea mentioned, enough to create

Input (3 segments): "the app crashes when I upload photos on my iPhone it happens every time I select a photo from gallery"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: Detailed problem with device and steps

Input (4 segments): "add voice commands for Uber rides so I can just say get me a ride to this location and it books the ride"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: Clear feature request with usage example

Input (5 segments): "the app crashes when uploading photos on iPhone every time from gallery. Hey what time is dinner tonight?"
Output:
COMPLETE: yes
ON_TOPIC: no
REASON: Issue complete but user moved to unrelated topic (dinner plans)

Input (2 segments): "test test test check check"
Output:
COMPLETE: no
ON_TOPIC: no
REASON: Meaningless testing phrase only

Input (2 segments): "what time is it where are you"
Output:
COMPLETE: no
ON_TOPIC: no
REASON: Personal conversation, not software related

Input (2 segments): "I want to maybe"
Output:
COMPLETE: yes
ON_TOPIC: yes
REASON: User starting to describe something, create issue anyway"""
                    },
                    {
                        "role": "user",
                        "content": f"Segments collected: {segment_count}\nAccumulated text: {accumulated_text}\n\nAnalyze:"
                    }
                ],
                temperature=0.2,
                max_tokens=100
            )
            
            result = response.choices[0].message.content.strip()
            
            # Parse response
            is_complete = "COMPLETE: yes" in result.lower()
            is_on_topic = "ON_TOPIC: yes" in result.lower()
            
            # Extract reason
            reason = ""
            for line in result.split('\n'):
                if line.startswith("REASON:"):
                    reason = line.replace("REASON:", "").strip()
                    break
            
            return {
                "is_complete": is_complete,
                "is_still_on_topic": is_on_topic,
                "reason": reason
            }
            
        except Exception as e:
            print(f"⚠️  AI completeness check failed: {e}", flush=True)
            # Default to continue collecting if check fails
            return {
                "is_complete": False,
                "is_still_on_topic": True,
                "reason": "Check failed, continuing collection"
            }
    
    @classmethod
    async def ai_generate_issue_from_segments(cls, all_segments_text: str) -> Tuple[str, str]:
        """
        Generate issue title and description from 5 segments of speech.
        AI intelligently extracts the problem and formats it properly.
        Also validates if this is actually a legitimate issue/feedback.
        Returns (title, description) or (None, None) if not a valid issue.
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a GitHub issue formatter with developer expertise. Extract feedback/problems from voice transcripts and format them as GitHub issues.

IMPORTANT VALIDATION:
- BE VERY LENIENT: Almost ALWAYS create an issue unless completely impossible
- Only return "NOT_AN_ISSUE" if it's truly meaningless gibberish or personal conversation
- If there's even a hint of a problem, feature, or idea - CREATE THE ISSUE
- Trust that the user triggered this for a reason - give them benefit of the doubt

Examples of NOT valid (ONLY these types):
- Pure testing: "test test test check check"
- Personal chat: "hey what's up how are you feeling today"
- Off-topic: "I need to buy groceries and pick up kids from school"

Examples of VALID (create issue for ALL of these):
- "app for rides" - YES! Create feature request
- "crashes sometimes" - YES! Create bug report  
- "I want to maybe add" - YES! Create feature idea
- "fix the thing" - YES! Create issue (AI will infer what "thing" means)
- Any mention of app/software/feature/bug/problem - YES!
- Brief/unclear descriptions - YES! (AI will format nicely)

IMPORTANT: Voice transcripts often have transcription errors. Think like a developer and use context to infer the correct meaning.

The user said "Feedback Post" and then described their problem. Create a clear GitHub issue.

Rules:
1. **Correct transcription errors using context**:
   - "heal an Uber" → "hail an Uber" (ride-hailing context)
   - "light" → "ride" (transportation context)
   - Think about what makes technical/logical sense
2. Generate a concise, descriptive title (max 80 characters)
3. Create a detailed description with:
   - Clear problem statement or feature request
   - Break into SEPARATE paragraphs (use blank lines between them)
   - Each paragraph should cover one aspect/point
   - Any mentioned steps or context
   - Expected vs actual behavior (if mentioned)
   - Use plain paragraphs (NO markdown headings like # or ##)
4. Remove filler words (um, uh, like, you know, basically, so)
5. Fix grammar and capitalization
6. Make it professional but preserve the user's intent
7. If technical details are mentioned, include them clearly
8. Format as clean paragraph text with proper spacing
9. End with blank line then footer: "Created via Omi"

Format your response EXACTLY like this:

If this is NOT a valid issue/feedback:
NOT_AN_ISSUE

If this IS a valid issue/feedback:
TITLE: <concise title here>
DESCRIPTION: <clean paragraph description - NO markdown headings or special formatting>

Created via Omi

Examples:

NOT VALID (accidental triggers):
Input: "test test test"
Output: NOT_AN_ISSUE

Input: "hey what's up how are you doing today"
Output: NOT_AN_ISSUE

Input: "I need to buy groceries later at the store"
Output: NOT_AN_ISSUE

Input: "checking if this works testing one two three"
Output: NOT_AN_ISSUE

VALID (legitimate issues/feedback):
Input: "heal an Uber light using the OMI app"
Context: User is talking about ride-hailing
Output:
TITLE: Add ability to hail Uber rides through Omi app
DESCRIPTION: Request to add functionality for hailing Uber rides directly through the Omi app using voice commands.

Users would be able to call for an Uber by speaking to their Omi device.

Created via Omi

Input: "the app keeps crashing whenever I try to upload a photo um it just freezes and then closes I'm using an iPhone 14 and it happens every single time"
Output:
TITLE: App crashes when uploading photos on iPhone 14
DESCRIPTION: The app consistently crashes during photo uploads. When attempting to upload a photo, the app freezes briefly and then closes completely.

This issue occurs every time on iPhone 14 and makes the photo upload feature unusable.

Created via Omi

Input: "I want this feature where we have an app for calling a ride on Uber just by saying get me a ride"
Output:
TITLE: Add voice command feature to call Uber rides
DESCRIPTION: Feature request to add voice command functionality for calling Uber rides.

Users should be able to say commands like "get me a ride to [location]" and have the app automatically book an Uber ride. This would make ride-hailing more convenient and hands-free.

Created via Omi

Now process the user's feedback:"""
                    },
                    {
                        "role": "user",
                        "content": f"Voice transcript after 'Feedback Post': {all_segments_text}\n\nGenerate the issue:"
                    }
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            result = response.choices[0].message.content.strip()
            
            # Check if AI determined this is not a valid issue
            if "NOT_AN_ISSUE" in result:
                print(f"🚫 AI determined this is not a valid issue: '{all_segments_text[:100]}'", flush=True)
                return None, None
            
            # Parse TITLE and DESCRIPTION
            title = ""
            description = ""
            
            lines = result.split('\n')
            current_section = None
            
            for line in lines:
                if line.startswith("TITLE:"):
                    title = line.replace("TITLE:", "").strip()
                    current_section = "title"
                elif line.startswith("DESCRIPTION:"):
                    description = line.replace("DESCRIPTION:", "").strip()
                    current_section = "description"
                elif current_section == "description" and line.strip():
                    description += "\n" + line.strip()
            
            # Fallback if parsing fails
            if not title:
                print(f"⚠️  AI did not return valid title/description", flush=True)
                return None, None
            if not description:
                description = all_segments_text
            
            # Ensure title is not too long
            if len(title) > 100:
                title = title[:97] + "..."
            
            return title, description.strip()
            
        except Exception as e:
            print(f"⚠️  AI generation failed: {e}, using basic formatting", flush=True)
            # Fallback
            title = "User Feedback"
            description = f"User Report:\n\n{all_segments_text}\n\nCreated via Omi"
            return title, description
    
    @classmethod
    async def ai_select_labels(cls, title: str, description: str, available_labels: list[str]) -> list[str]:
        """
        Let AI select the most appropriate labels from available repo labels.
        Returns list of selected label names (max 3).
        """
        if not available_labels:
            return []
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a GitHub issue labeling assistant. Given an issue title, description, and available labels, select the most appropriate labels.

CRITICAL RULES:
1. ONLY use labels from the provided available list - DO NOT make up new labels
2. Select 1-3 labels maximum (prefer 1-2)
3. Match labels EXACTLY as they appear in the available list (case-sensitive, including hyphens/spaces)
4. Return ONLY the exact label names from the list, comma-separated, nothing else
5. If no labels fit well, return "none"

Examples:

Available: ["bug", "enhancement", "documentation", "help wanted"]
Issue: "App crashes when clicking submit button"
Response: bug

Available: ["bug", "feature-request", "iOS", "Android", "backend"]
Issue: "Add dark mode support for iPhone users"
Response: feature-request, iOS

Available: ["docs", "api", "frontend"]
Issue: "Update API documentation for new endpoints"
Response: docs, api

Available: ["bug", "mobile", "Feature Request"]
Issue: "App crashes on mobile"
Response: bug, mobile

Remember: Copy the label names EXACTLY as they appear in the available list!"""
                    },
                    {
                        "role": "user",
                        "content": f"""Available labels (copy these EXACTLY): {', '.join(available_labels)}

Issue Title: {title}
Issue Description: {description}

Select the most appropriate labels (use EXACT names from above):"""
                    }
                ],
                temperature=0.1,
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            
            if result.lower() == "none" or not result:
                return []
            
            # Parse comma-separated labels
            selected_labels = [label.strip() for label in result.split(',')]
            print(f"🤖 AI returned labels: {selected_labels}", flush=True)
            
            # Validate labels exist in available_labels (exact match and fuzzy match)
            available_labels_set = set(available_labels)
            available_labels_lower = {label.lower(): label for label in available_labels}
            valid_labels = []
            
            for label in selected_labels:
                matched = False
                # First try exact match
                if label in available_labels_set:
                    valid_labels.append(label)
                    matched = True
                    print(f"  ✅ '{label}' matched exactly", flush=True)
                # Then try case-insensitive match
                elif label.lower() in available_labels_lower:
                    matched_label = available_labels_lower[label.lower()]
                    valid_labels.append(matched_label)
                    matched = True
                    print(f"  ✅ '{label}' matched as '{matched_label}' (case-insensitive)", flush=True)
                # Try matching with spaces/hyphens normalized
                else:
                    normalized_label = label.lower().replace(' ', '-')
                    for avail_label in available_labels:
                        if avail_label.lower().replace(' ', '-') == normalized_label:
                            valid_labels.append(avail_label)
                            matched = True
                            print(f"  ✅ '{label}' matched as '{avail_label}' (normalized)", flush=True)
                            break
                
                if not matched:
                    print(f"  ❌ '{label}' not found in available labels - SKIPPING", flush=True)
                
                if len(valid_labels) >= 3:  # Max 3 labels
                    break
            
            return valid_labels
            
        except Exception as e:
            print(f"⚠️  AI label selection failed: {e}", flush=True)
            return []
    
    @classmethod
    def clean_content(cls, content: str) -> str:
        """Basic cleaning of content (fallback)."""
        # Remove multiple spaces
        content = re.sub(r'\s+', ' ', content)
        
        # Remove common filler words
        filler_words = ["um", "uh", "like", "you know", "so", "yeah"]
        words = content.split()
        cleaned_words = [w for w in words if w.lower().rstrip('.,!?') not in filler_words]
        
        content = ' '.join(cleaned_words).strip()
        
        # Ensure proper capitalization of first letter
        if content and content[0].islower():
            content = content[0].upper() + content[1:]
        
        return content

