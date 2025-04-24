from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv
import json
import uuid
from typing import Dict, List, Optional, Set, Any
import time
import random
import string
from datetime import datetime

load_dotenv()  # Load environment variables for other configurations

app = FastAPI()

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # adjust this in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
QUESTIONS_FILE = "quiz_data.json"

# Custom JSON encoder to handle sets
class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

# In-memory database for rooms and users
rooms: Dict[str, dict] = {}
users: Dict[str, dict] = {}

# Load existing data from JSON file if it exists
try:
    with open(QUESTIONS_FILE, "r") as f:
        data = json.load(f)
        rooms = data.get("rooms", {})
        users = data.get("users", {})
        
        # Convert lists back to sets for answered_correctly
        for room_id, room_data in rooms.items():
            if "answered_correctly" in room_data:
                for username, answered_list in room_data["answered_correctly"].items():
                    room_data["answered_correctly"][username] = set(answered_list)
except (FileNotFoundError, json.JSONDecodeError):
    pass

def save_data():
    """Save data to JSON file"""
    # Create a deep copy to avoid modifying the original data
    data_to_save = {
        "rooms": {room_id: room_data.copy() for room_id, room_data in rooms.items()},
        "users": users.copy()
    }
    
    # Convert sets to lists for JSON serialization
    for room_id, room_data in data_to_save["rooms"].items():
        if "answered_correctly" in room_data:
            room_data["answered_correctly"] = {
                username: list(answered_set) 
                for username, answered_set in room_data["answered_correctly"].items()
            }
    
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(data_to_save, f, cls=SetEncoder)

class RoomCreate(BaseModel):
    name: str
    topic: str
    max_players: Optional[int] = 10
    rounds: Optional[int] = 5
    api_key: str  # Required API key field for OpenRouter

class UserCreate(BaseModel):
    username: str

class AnswerSubmit(BaseModel):
    room_id: str
    user_id: str
    question_id: str
    answer: str

class ScoreUpdate(BaseModel):
    room_id: str
    user_id: str
    points: int = 1

class StartQuiz(BaseModel):
    room_id: str
    admin_id: str

# Generate a random room code of specified length
def generate_room_code(length=5):
    """Generate a random room code of specified length"""
    # Use uppercase letters and numbers but exclude confusing characters like O, 0, I, 1
    characters = ''.join(set(string.ascii_uppercase + string.digits) - set('O0I1'))
    return ''.join(random.choice(characters) for _ in range(length))

async def get_current_trends():
    """Fetch current trending topics from Twitter or use a fallback"""
    try:
        # In a real implementation, you would call the Twitter API here
        # For demo purposes, we'll use a static list that changes based on the day/time
        now = datetime.now()
        day_of_week = now.weekday()
        hour = now.hour
        
        # These would be replaced with actual API calls to Twitter's trends endpoint
        general_trends = [
            "#SongkranCTWxFB",
            "#Coachella2025",
            "#AprilFoolsDay",
            "#LISACHELLA",
            "#Perfect10LinersFinalEP",
            "#ElonMusk",
            "#ENCHELLA", 
            "#PahalgamTerroristAttack",
            "#ENHYPEN", 
            "#NintendoSwitch2"
        ]
        
        # Add some time-based variations to simulate dynamic trends
        if day_of_week == 0:  # Monday
            general_trends.extend(["#MondayMotivation", "#NewWeekNewGoals"])
        elif day_of_week == 4:  # Friday
            general_trends.extend(["#FridayFeeling", "#WeekendVibes"])
            
        if hour < 12:
            general_trends.append("#MorningRoutine")
        else:
            general_trends.append("#EveningVibes")
            
        return general_trends
        
    except Exception as e:
        print(f"Error fetching trends: {str(e)}")
        return [
            "#SongkranCTWxFB",
            "#Coachella2025",
            "#AprilFoolsDay",
            "#LISACHELLA",
            "#Perfect10LinersFinalEP"
        ]

async def generate_questions(topic: str, count: int = 5, api_key: str = None) -> List[dict]:
    """Generate stock market quiz questions using OpenRouter API"""
    print(f"Starting generate_questions for topic: {topic}, count: {count}")
    try:
        print("Preparing API request headers and payload")
        
        if not api_key:
            raise ValueError("API key not provided")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        prompt = (
    f"Generate 5 multiple-choice questions in JSON format about {topic}. "
    "Include specific company names, stock symbols, and percentage changes. "
    'Format as: {"questions":[{"text":"Question","options":["A","B"],"correct_answer":"A","difficulty":"medium","explanation":"Brief reason"}]}'
)
        
        payload = {
            "model": "openai/gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        print("Sending API request to OpenRouter")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=15.0
                )
                print(f"API response status: {response.status_code}")
                print(f"API response body: {response.text}")
                response.raise_for_status()
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as timeout_err:
                print(f"Timeout occurred, retrying with longer timeout: {str(timeout_err)}")
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                print(f"Retry API response status: {response.status_code}")
                print(f"Retry API response body: {response.text}")
                response.raise_for_status()
            except httpx.HTTPStatusError as http_err:
                print(f"HTTP error occurred: {str(http_err)}")
                raise
            
            print("Parsing API response")
            result = response.json()
            if "choices" not in result:
                print(f"Error: 'choices' key missing in API response: {result}")
                raise KeyError(f"'choices' key missing in API response: {result}")
            content = json.loads(result["choices"][0]["message"]["content"])
            questions = content.get("questions", [])
            print(f"Received {len(questions)} questions from API: {questions}")
            
            # Validate and transform questions
            validated_questions = []
            for q in questions:
                if not all(k in q for k in ["text", "options", "correct_answer", "difficulty", "explanation"]):
                    print(f"Skipping invalid question: {q}")
                    continue
                
                if len(set(q["options"])) != len(q["options"]) or q["correct_answer"] not in q["options"]:
                    print(f"Skipping question with invalid options or correct_answer: {q}")
                    continue
                
                validated_questions.append({
                    "id": str(uuid.uuid4()),
                    "text": q["text"],
                    "options": q["options"],
                    "correct_answer": q["correct_answer"],
                    "difficulty": q["difficulty"],
                    "category": "stock market",
                    "explanation": q["explanation"],
                    "timestamp": time.time()
                })
            
            print(f"Validated {len(validated_questions)} questions")
            while len(validated_questions) < count:
                print("Adding fallback question due to insufficient valid questions")
                validated_questions.append({
                    "id": str(uuid.uuid4()),
                    "text": "Which company saw the largest stock price increase in the last 24 hours?",
                    "options": ["Apple (AAPL)", "Microsoft (MSFT)", "Tesla (TSLA)", "Amazon (AMZN)"],
                    "correct_answer": "Tesla (TSLA)",
                    "difficulty": "medium",
                    "category": "stock market",
                    "explanation": "Tesla's stock surged due to positive EV market news.",
                    "timestamp": time.time()
                })
            
            print(f"Returning {len(validated_questions[:count])} questions")
            return validated_questions[:count]
            
    except Exception as e:
        print(f"Error generating stock market questions: {str(e)}")
        print("Falling back to default questions")
        fallback_questions = [
            {
                "id": str(uuid.uuid4()),
                "text": "Which company's stock surged after a major product announcement?",
                "options": ["Apple (AAPL)", "Microsoft (MSFT)", "Tesla (TSLA)", "Amazon (AMZN)"],
                "correct_answer": "Apple (AAPL)",
                "difficulty": "medium",
                "category": "stock market",
                "explanation": "Apple announced a new product line, boosting its stock.",
                "timestamp": time.time()
            },
            {
                "id": str(uuid.uuid4()),
                "text": "Which stock fell due to a recent earnings miss?",
                "options": ["Google (GOOGL)", "Facebook (META)", "Netflix (NFLX)", "Intel (INTC)"],
                "correct_answer": "Netflix (NFLX)",
                "difficulty": "medium",
                "category": "stock market",
                "explanation": "Netflix reported lower-than-expected subscriber growth.",
                "timestamp": time.time()
            },
            {
                "id": str(uuid.uuid4()),
                "text": "What's the typical price-to-earnings (P/E) ratio for a growth stock?",
                "options": ["5-10", "15-25", "30-50", "Over 100"],
                "correct_answer": "30-50",
                "difficulty": "medium",
                "category": "stock market",
                "explanation": "Growth stocks typically have higher P/E ratios due to expected future earnings.",
                "timestamp": time.time()
            },
            {
                "id": str(uuid.uuid4()),
                "text": "Which financial metric is most important when evaluating dividend stocks?",
                "options": ["Dividend Yield", "Price-to-Book Ratio", "Beta", "Return on Equity"],
                "correct_answer": "Dividend Yield",
                "difficulty": "easy",
                "category": "stock market",
                "explanation": "Dividend yield indicates how much a company pays out in dividends relative to its share price.",
                "timestamp": time.time()
            },
            {
                "id": str(uuid.uuid4()),
                "text": "What typically happens to bond prices when interest rates rise?",
                "options": ["They rise", "They fall", "They remain unchanged", "They become more volatile"],
                "correct_answer": "They fall",
                "difficulty": "medium",
                "category": "stock market",
                "explanation": "Bond prices have an inverse relationship with interest rates.",
                "timestamp": time.time()
            }
        ]
        return fallback_questions[:count]

@app.post("/create-room")
async def create_room(room: RoomCreate, request: Request):
    """Create a new quiz room with generated questions and short room code"""
    # Generate a short room code instead of UUID
    room_code = generate_room_code(5)
    
    # Make sure the code is unique
    while room_code in rooms:
        room_code = generate_room_code(5)
    
    if any(r["name"] == room.name for r in rooms.values()):
        raise HTTPException(status_code=400, detail="Room name already exists")
    
    # Generate dynamic questions with the provided API key
    questions = await generate_questions(room.topic, room.rounds, api_key=room.api_key)
    
    # Debug print to see what questions were generated
    print(f"Generated {len(questions)} questions for room {room_code}")
    if questions:
        print(f"Sample question: {questions[0]}")
    
    # Create admin user
    admin_id = str(uuid.uuid4())
    admin_username = f"Admin-{room_code[:3]}"
    
    users[admin_id] = {
        "id": admin_id,
        "username": admin_username,
        "current_room": room_code,
        "score": 0,
        "is_admin": True,
        "joined_at": time.time()
    }
    
    # Create the room
    rooms[room_code] = {
        "id": room_code,
        "name": room.name,
        "topic": room.topic,
        "max_players": room.max_players,
        "questions": questions,
        "players": [admin_username],
        "admin_id": admin_id,
        "current_question": 0,
        "scores": {admin_username: 0},
        "started": False,
        "created_at": time.time(),
        "answered_correctly": {admin_username: set()}
    }
    
    save_data()
    
    return {
        "message": f"Room '{room.name}' created successfully. You are the admin.",
        "room_id": room_code,
        "admin_id": admin_id,
        "admin_username": admin_username,
        "topic": room.topic,
        "questions_count": len(questions)
    }

@app.post("/join-room/{room_id}")
async def join_room(room_id: str, user: UserCreate):
    """Join an existing quiz room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    
    # Debug print to see what's in the room
    print(f"Room data: {json.dumps({k: v for k, v in room.items() if k != 'questions'}, cls=SetEncoder)}")
    print(f"Questions count: {len(room.get('questions', []))}")
    if 'questions' in room and len(room['questions']) > 0:
        print(f"First question sample: {room['questions'][0]}")
    
    if len(room["players"]) >= room["max_players"]:
        raise HTTPException(status_code=400, detail="Room is full")
    
    # Check if username is already taken in this room
    if user.username in room["players"]:
        # Check if the user already exists
        existing_user_id = None
        for uid, u in users.items():
            if u.get("username") == user.username and u.get("current_room") == room_id:
                existing_user_id = uid
                break
        
        if existing_user_id:
            # Return the existing user info
            user_info = users[existing_user_id]
            
            # Make sure we have questions to return
            questions_to_return = []
            if 'questions' in room and isinstance(room['questions'], list):
                questions_to_return = [
                    {
                        "question_id": q.get("id", ""),
                        "text": q.get("text", ""),
                        "options": q.get("options", [])
                    } for q in room["questions"]
                ]
            
            is_admin = user_info.get("is_admin", False)
            
            return {
                "message": f"User '{user.username}' already in room '{room['name']}'.",
                "user_id": existing_user_id,
                "is_admin": is_admin,
                "players": room["players"],
                "questions": questions_to_return,
                "room_status": {
                    "started": room["started"],
                    "current_question": room["current_question"],
                    "total_questions": len(room.get("questions", [])),
                    "waiting_for_admin": not room["started"]
                },
                "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
            }
        else:
            raise HTTPException(status_code=400, detail="Username already taken in this room")
    
    # Create or update user
    user_id = str(uuid.uuid4())
    users[user_id] = {
        "id": user_id,
        "username": user.username,
        "current_room": room_id,
        "score": 0,
        "is_admin": False,  # Normal user, not admin
        "joined_at": time.time()
    }
    
    # Add user to room
    room["players"].append(user.username)
    room["scores"][user.username] = 0
    
    # Initialize answered_correctly tracking for this user
    if "answered_correctly" not in room:
        room["answered_correctly"] = {}
    room["answered_correctly"][user.username] = set()
    
    save_data()
    
    # Ensure we have questions to return
    questions_to_return = []
    if 'questions' in room and isinstance(room['questions'], list):
        questions_to_return = [
            {
                "question_id": q.get("id", ""),
                "text": q.get("text", ""),
                "options": q.get("options", [])
            } for q in room["questions"]
        ]
    else:
        # If no questions exist, let's log this
        print(f"WARNING: No questions found for room {room_id}")
    
    # Return room info including questions but without correct answers
    return {
        "message": f"User '{user.username}' joined room '{room['name']}'.",
        "user_id": user_id,
        "is_admin": False,
        "players": room["players"],
        "questions": questions_to_return,
        "room_status": {
            "started": room["started"],
            "current_question": room["current_question"],
            "total_questions": len(room.get("questions", [])),
            "waiting_for_admin": not room["started"]
        },
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/start-quiz")
async def start_quiz(start: StartQuiz):
    """Start the quiz (admin only)"""
    if start.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[start.room_id]
    
    # Check if the user is the admin
    if room.get("admin_id") != start.admin_id:
        raise HTTPException(status_code=403, detail="Only the admin can start the quiz")
    
    # Start the quiz
    room["started"] = True
    save_data()
    
    return {
        "message": "Quiz started successfully!",
        "room_id": start.room_id,
        "started": True,
        "players_count": len(room["players"])
    }

@app.get("/room-status/{room_id}")
async def get_room_status(room_id: str):
    """Get current status of a room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    return {
        "name": room["name"],
        "topic": room["topic"],
        "players": room["players"],
        "current_question": room["current_question"],
        "total_questions": len(room["questions"]),
        "scores": room["scores"],
        "started": room["started"],
        "admin_id": room["admin_id"],
        "waiting_for_admin": not room["started"],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/update-score")
async def update_score(score_update: ScoreUpdate):
    """Update a user's score and return the updated leaderboard"""
    if score_update.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    if score_update.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    room = rooms[score_update.room_id]
    user = users[score_update.user_id]
    
    # Update user score
    user_name = user["username"]
    room["scores"][user_name] = room["scores"].get(user_name, 0) + score_update.points
    user["score"] += score_update.points
    
    save_data()
    
    return {
        "username": user_name,
        "new_score": room["scores"][user_name],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/submit-answer")
async def submit_answer(answer: AnswerSubmit):
    """Submit an answer to a question and automatically update score if correct"""
    if answer.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    if answer.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    room = rooms[answer.room_id]
    user = users[answer.user_id]
    user_name = user["username"]
    
    if not room["started"]:
        raise HTTPException(status_code=400, detail="Quiz hasn't started yet. Waiting for admin to start.")
    
    # Find the question
    question = next((q for q in room["questions"] if q["id"] == answer.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # Ensure we have a set to track answered questions
    if "answered_correctly" not in room:
        room["answered_correctly"] = {}
    if user_name not in room["answered_correctly"]:
        room["answered_correctly"][user_name] = set()
    
    # Check if user already answered this question correctly
    already_answered = answer.question_id in room["answered_correctly"][user_name]
    if already_answered:
        return {
            "correct": False,
            "already_answered": True,
            "message": "You've already answered this question correctly.",
            "current_score": room["scores"][user_name],
            "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
        }
    
    # Check if answer is correct
    is_correct = answer.answer.lower() == question["correct_answer"].lower()
    
    # Automatically update score if correct
    if is_correct:
        # Add 1 point to the user's score
        room["scores"][user_name] = room["scores"].get(user_name, 0) + 1
        user["score"] += 1
        
        # Mark question as correctly answered by this user
        room["answered_correctly"][user_name].add(answer.question_id)
    
    save_data()
    
    return {
        "correct": is_correct,
        "correct_answer": question["correct_answer"],
        "points_earned": 1 if is_correct else 0,
        "current_score": room["scores"][user_name],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.get("/leaderboard/{room_id}")
async def get_leaderboard(room_id: str):
    """Get the current leaderboard for a room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    
    return {
        "room_name": room["name"],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.on_event("shutdown")
def shutdown_event():
    """Save data when the application shuts down"""
    save_data()