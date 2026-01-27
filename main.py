"""
Main entry point - runs both Vocab Learner and Review bots together.
"""
import subprocess
import sys
import os
import signal

def main():
    print("Starting both bots...")

    # Start both bot processes
    bot_process = subprocess.Popen([sys.executable, "bot.py"])
    review_process = subprocess.Popen([sys.executable, "review_bot.py"])

    print(f"Vocab Learner bot PID: {bot_process.pid}")
    print(f"Review bot PID: {review_process.pid}")

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        print("\nShutting down bots...")
        bot_process.terminate()
        review_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Wait for both processes
    try:
        bot_process.wait()
        review_process.wait()
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
