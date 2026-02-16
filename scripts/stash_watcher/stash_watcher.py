#!/usr/bin/python3
import builtins
from pathlib import Path
import os
import time
import subprocess
import sys
import traceback
import threading

# Ensure print statements are flushed immediately (important for Docker logs)
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver as Observer
    import stash_worker
except Exception:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "watchdog"])
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver as Observer
    import stash_worker


# Poll interval in seconds (default: 30 minutes)
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30 * 60))
DATA_ROOT = os.getenv("DATA_ROOT")
if DATA_ROOT:
    (Path(DATA_ROOT) / "torrents-stash/.downloading/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/.torrents/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/tv-whisparr/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/whisparr/").mkdir(parents=True, exist_ok=True)
    

class BackgroundPoller(threading.Thread):
    """Background thread that periodically runs the stash worker."""

    def __init__(self, interval: int = POLL_INTERVAL):
        super().__init__(daemon=True, name="BackgroundPoller")
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        print(f"Background poller started, will run every {self.interval} seconds")
        while not self._stop_event.is_set():
            # Wait for the interval (or until stopped)
            if self._stop_event.wait(timeout=self.interval):
                break
            try:
                print(f"[BackgroundPoller] Running scheduled scan at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                stash_worker.main()
                print(f"[BackgroundPoller] Scheduled scan completed at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                print(f"[BackgroundPoller] Error during scheduled scan: {e}")
                print(traceback.format_exc())


class Watcher:
    def __init__(self):
        self.observer = Observer()
        self.poller = BackgroundPoller()
        # make sure each of the directories exists
        # create them if they don't
        self.directories_to_watch = stash_worker.get_watch_directories()

        for directory in self.directories_to_watch:
            if not os.path.exists(directory):
                try:
                    os.makedirs(directory)
                except OSError as e:
                    print(f"Error creating directory {directory}: {e}")
                    print(traceback.format_exc())

    def run(self):
        event_handler = Handler()
        for directory in self.directories_to_watch:
            assert os.path.exists(directory), f"Directory {directory} does not exist"
            self.observer.schedule(event_handler, directory, recursive=True)
        self.observer.start()
        self.poller.start()
        try:
            print("Watching directories for new files...", self.directories_to_watch)
            print(f"Background polling enabled every {POLL_INTERVAL} seconds ({POLL_INTERVAL // 60} minutes)")
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            self.poller.stop()
            self.observer.stop()
        self.observer.join()


class Handler(FileSystemEventHandler):
    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return None
        else:
            print(f"New file created: {event.src_path}")
            stash_worker.main([event.src_path])

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return None
        else:
            print(f"File moved: {event.src_path}")
            stash_worker.main([event.src_path])

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Catch-all event handler.
        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
        """

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Called when a file or directory is deleted.

        :param event:
            Event representing file/directory deletion.
        :type event:
            :class:`DirDeletedEvent` or :class:`FileDeletedEvent`
        """

    def on_modified(self, event: FileSystemEvent) -> None:
        """Called when a file or directory is modified.

        :param event:
            Event representing file/directory modification.
        :type event:
            :class:`DirModifiedEvent` or :class:`FileModifiedEvent`
        """
        if event.is_directory:
            return None
        else:
            print(f"File moved: {event.src_path}")
            stash_worker.main([event.src_path])

    def on_closed(self, event: FileSystemEvent) -> None:
        """Called when a file opened for writing is closed.

        :param event:
            Event representing file closing.
        :type event:
            :class:`FileClosedEvent`
        """

    def on_opened(self, event: FileSystemEvent) -> None:
        """Called when a file is opened.

        :param event:
            Event representing file opening.
        :type event:
            :class:`FileOpenedEvent`
        """


if __name__ == "__main__":
    print("running initial worker")
    stash_worker.main()
    print("Starting watcher...")
    w = Watcher()
    w.run()
