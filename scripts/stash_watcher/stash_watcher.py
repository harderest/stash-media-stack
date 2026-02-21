#!/usr/bin/python3
import builtins
from pathlib import Path
import os
import stat
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
TARGET_UID = int(os.environ.get("FIX_PERMS_UID", 1000))
TARGET_GID = int(os.environ.get("FIX_PERMS_GID", 1000))

# Directories to fix permissions on
PERMS_DIRS = ["/provision", "/data/torrents-stash"]

if DATA_ROOT:
    (Path(DATA_ROOT) / "torrents-stash/.downloading/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/.torrents/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/tv-whisparr/").mkdir(parents=True, exist_ok=True)
    (Path(DATA_ROOT) / "torrents-stash/whisparr/").mkdir(parents=True, exist_ok=True)


def fix_permissions(dirs=PERMS_DIRS):
    """Fix ownership and permissions so all containers (UID 1000) can access files.

    - chown everything to TARGET_UID:TARGET_GID
    - dirs: 2775 (rwxrwsr-x, setgid so new files inherit group)
    - files: 0664 (rw-rw-r--)
    Requires CAP_CHOWN, CAP_FOWNER, CAP_DAC_OVERRIDE.
    """
    fixed = 0
    errors = 0
    for root_dir in dirs:
        if not os.path.exists(root_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Fix directory
            try:
                st = os.stat(dirpath)
                needs_chown = st.st_uid != TARGET_UID or st.st_gid != TARGET_GID
                # 2775 = rwxrwsr-x (setgid)
                needs_chmod = (st.st_mode & 0o7777) != 0o2775
                if needs_chown:
                    os.chown(dirpath, TARGET_UID, TARGET_GID)
                    fixed += 1
                if needs_chmod:
                    os.chmod(dirpath, 0o2775)
                    fixed += 1
            except OSError as e:
                errors += 1
                if errors <= 5:
                    print(f"[PermFix] Error on dir {dirpath}: {e}")

            # Fix files
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    st = os.lstat(fpath)
                    if stat.S_ISLNK(st.st_mode):
                        continue
                    needs_chown = st.st_uid != TARGET_UID or st.st_gid != TARGET_GID
                    # 0664 = rw-rw-r--
                    needs_chmod = (st.st_mode & 0o7777) != 0o0664
                    if needs_chown:
                        os.chown(fpath, TARGET_UID, TARGET_GID)
                        fixed += 1
                    if needs_chmod:
                        os.chmod(fpath, 0o0664)
                        fixed += 1
                except OSError as e:
                    errors += 1
                    if errors <= 5:
                        print(f"[PermFix] Error on file {fpath}: {e}")

    if fixed > 0 or errors > 0:
        print(f"[PermFix] Done: {fixed} fixes applied, {errors} errors")
    else:
        print(f"[PermFix] All permissions OK")


class BackgroundPoller(threading.Thread):
    """Background thread that periodically runs the stash worker and fixes permissions."""

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
                fix_permissions()
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


def fix_single_path(path):
    """Fix ownership/permissions on a single file or directory."""
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return
        if st.st_uid != TARGET_UID or st.st_gid != TARGET_GID:
            os.chown(path, TARGET_UID, TARGET_GID)
        if stat.S_ISDIR(st.st_mode):
            if (st.st_mode & 0o7777) != 0o2775:
                os.chmod(path, 0o2775)
        else:
            if (st.st_mode & 0o7777) != 0o0664:
                os.chmod(path, 0o0664)
    except OSError:
        pass  # best-effort, full fix runs on poll


class Handler(FileSystemEventHandler):
    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return None
        else:
            print(f"New file created: {event.src_path}")
            fix_single_path(event.src_path)
            fix_single_path(os.path.dirname(event.src_path))
            stash_worker.main([event.src_path])

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return None
        else:
            print(f"File moved: {event.src_path}")
            fix_single_path(event.src_path)
            fix_single_path(os.path.dirname(event.src_path))
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
    print("Fixing permissions on startup...")
    fix_permissions()
    print("running initial worker")
    stash_worker.main()
    print("Starting watcher...")
    w = Watcher()
    w.run()
