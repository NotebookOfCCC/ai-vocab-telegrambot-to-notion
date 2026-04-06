"""
Main Entry Point

Runs all five Telegram bots as separate processes:
1. bot.py - Vocab Learner Bot (AI-powered vocabulary learning)
2. review_bot.py - Review Bot (spaced repetition reviews)
3. habit_bot.py - Habit Bot (daily practice reminders)
4. grammar_bot.py - Grammar Drill Bot (grammar practice from Obsidian)
5. news_bot.py - News Digest Bot (daily AI builder digests)

Usage: python main.py

Each bot runs independently and can be stopped/started separately.
Graceful shutdown on SIGTERM or SIGINT (Ctrl+C).
"""
import subprocess
import sys
import os
import signal

def main():
    print("Starting all bots...")

    # Start all bot processes
    bot_process = subprocess.Popen([sys.executable, "vocab/bot.py"])
    review_process = subprocess.Popen([sys.executable, "review/review_bot.py"])
    habit_process = subprocess.Popen([sys.executable, "habit/habit_bot.py"])
    grammar_process = subprocess.Popen([sys.executable, "grammar/grammar_bot.py"])
    news_process = subprocess.Popen([sys.executable, "news/news_bot.py"])

    print(f"Vocab Learner bot PID: {bot_process.pid}")
    print(f"Review bot PID: {review_process.pid}")
    print(f"Habit bot PID: {habit_process.pid}")
    print(f"Grammar Drill bot PID: {grammar_process.pid}")
    print(f"News Digest bot PID: {news_process.pid}")

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        print("\nShutting down bots...")
        bot_process.terminate()
        review_process.terminate()
        habit_process.terminate()
        grammar_process.terminate()
        news_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Wait for all processes
    try:
        bot_process.wait()
        review_process.wait()
        habit_process.wait()
        grammar_process.wait()
        news_process.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
