"""
Main Entry Point

Runs all three Telegram bots as separate processes:
1. bot.py - Vocab Learner Bot (AI-powered vocabulary learning)
2. review_bot.py - Review Bot (spaced repetition reviews)
3. habit_bot.py - Habit Bot (daily practice reminders)

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
    bot_process = subprocess.Popen([sys.executable, "bot.py"])
    review_process = subprocess.Popen([sys.executable, "review_bot.py"])
    habit_process = subprocess.Popen([sys.executable, "habit_bot.py"])

    print(f"Vocab Learner bot PID: {bot_process.pid}")
    print(f"Review bot PID: {review_process.pid}")
    print(f"Habit bot PID: {habit_process.pid}")

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        print("\nShutting down bots...")
        bot_process.terminate()
        review_process.terminate()
        habit_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Wait for all processes
    try:
        bot_process.wait()
        review_process.wait()
        habit_process.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
