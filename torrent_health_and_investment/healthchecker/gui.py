import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from threading import Thread, Event
import time
from datetime import datetime
from typing import Optional

from healthchecker.db import get_latest_seeding_levels, init_db
from healthchecker.sampler import HealthChecker


class SwarmHealthGUI:

    def __init__(self, csv_path: str = "torrents.csv", mode: str = "csv"):
        self.csv_path = csv_path
        self.mode = mode
        self.checker: Optional[HealthChecker] = None
        self.running = Event()
        self.refresh_thread: Optional[Thread] = None
        
        # Initialize database
        init_db()
        
        # Create main window
        self.root = ttk.Tk()
        self.root.title("SwarmHealth - Seeding Level Monitor")
        self.root.geometry("1200x800")
        
        # Configure style
        style = ttk.Style("darkly")
        
        self.setup_ui()
        self.start_refresh_loop()
        
    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        title_label = ttk.Label(
            main_frame, 
            text="SwarmHealth - Creative Commons Torrent Monitor",
            font=("Ãrial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Control panel
        control_frame = ttk.Labelframe(main_frame, text="Controls", padding="10")
        control_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.start_button = ttk.Button(
            control_frame,
            text="▶ Start Health Checker",
            command=self.toggle_checker
        )
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.refresh_button = ttk.Button(
            control_frame,
            text="Refresh Data",
            command=self.refresh_data
        )
        self.refresh_button.grid(row=0, column=1, padx=5)
        
        self.status_label = ttk.Label(
            control_frame,
            text="Status: Stopped",
            foreground="red"
        )
        self.status_label.grid(row=0, column=2, padx=20)
        
        # Statistics frame
        stats_frame = ttk.Labelframe(main_frame, text="Statistics", padding="10")
        stats_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.total_label = ttk.Label(stats_frame, text="Total Entries: 0", font=("Arial", 10))
        self.total_label.grid(row=0, column=0, padx=10)
        
        self.healthy_label = ttk.Label(stats_frame, text="Healthy: 0", font=("Arial", 10), foreground="green")
        self.healthy_label.grid(row=0, column=1, padx=10)
        
        self.unhealthy_label = ttk.Label(stats_frame, text="No Peers: 0", font=("Arial", 10), foreground="red")
        self.unhealthy_label.grid(row=0, column=2, padx=10)
        
        self.exploding_label = ttk.Label(stats_frame, text="Exploding: 0", font=("Arial", 10), foreground="orange")
        self.exploding_label.grid(row=0, column=3, padx=10)
        
        # Tree view for torrents
        tree_frame = ttk.Frame(main_frame)
        tree_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        main_frame.rowconfigure(3, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        # Create treeview with scrollbars
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        
        columns = ("Infohash", "Seeders", "Leechers", "Total", "Growth", "Shrink", "Exploding", "Status", "Last Check")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", 
                                 yscrollcommand=tree_scroll_y.set,
                                 xscrollcommand=tree_scroll_x.set)

        for col in columns:
            self.tree.heading(col, text=col, command=lambda _col=col: \
                self.treeview_sort_column(self.tree, _col, False))
        
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)
        
        # Configure columns
        self.tree.heading("Infohash", text="Infohash")
        self.tree.heading("Seeders", text="Seeders")
        self.tree.heading("Leechers", text="Leechers")
        self.tree.heading("Total", text="Total Peers")
        self.tree.heading("Growth", text="Growth %")
        self.tree.heading("Shrink", text="Shrink %")
        self.tree.heading("Exploding", text="Exploding")
        self.tree.heading("Status", text="Status")
        self.tree.heading("Last Check", text="Last Check")
        
        self.tree.column("Infohash", width=150)
        self.tree.column("Seeders", width=80)
        self.tree.column("Leechers", width=80)
        self.tree.column("Total", width=80)
        self.tree.column("Growth", width=80)
        self.tree.column("Shrink", width=80)
        self.tree.column("Exploding", width=80)
        self.tree.column("Status", width=100)
        self.tree.column("Last Check", width=150)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        tree_scroll_x.grid(row=1, column=0, sticky=(tk.W, tk.E))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        # Log area
        log_frame = ttk.Labelframe(main_frame, text="Log", padding="10")
        log_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        main_frame.rowconfigure(4, weight=1)
        
        self.log_text = ScrolledText(log_frame, height=8, wrap=tk.WORD, autohide=True)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        
        # Initial data load
        self.refresh_data()

    def treeview_sort_column(self,tv, col, reverse):
        l = [(tv.set(k, col), k) for k in tv.get_children('')]
        l.sort(reverse=reverse)

        # rearrange items in sorted positions
        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # reverse sort next time
        tv.heading(col, command=lambda: \
                self.treeview_sort_column(tv, col, not reverse))
        
    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        
    def refresh_data(self):
        try:
            data = get_latest_seeding_levels(limit=1000)
            
            # Clear existing items
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            # Update statistics
            total = len(data)
            healthy = sum(1 for d in data if d.get("total_peers", 0) > 0)
            unhealthy = total - healthy
            exploding = sum(1 for d in data if d.get("exploding_estimator", 0) > 50)
            
            self.total_label.config(text=f"Total Entries: {total}")
            self.healthy_label.config(text=f"Healthy: {healthy}")
            self.unhealthy_label.config(text=f"No Peers: {unhealthy}")
            self.exploding_label.config(text=f"Exploding: {exploding}")
            
            # Add items to tree
            for entry in data:
                total_peers = entry.get("total_peers", 0) or entry.get("peers", 0)
                seeders = entry.get("seeders", 0)
                leechers = entry.get("leechers", 0)
                growth = entry.get("growth", 0.0)
                shrink = entry.get("shrink", 0.0)
                exploding_est = entry.get("exploding_estimator", 0.0)
                
                status = "Healthy" if total_peers > 0 else "No Peers"
                
                last_check = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                
                # Format values
                infohash_display = entry["infohash"][:12] + "..." if len(entry["infohash"]) > 12 else entry["infohash"]
                growth_str = f"{growth:+.1f}%" if growth != 0 else "0%"
                shrink_str = f"{shrink:.1f}%" if shrink > 0 else "0%"
                exploding_str = f"{exploding_est:.1f}" if exploding_est > 0 else "0"
                
                item = self.tree.insert("", tk.END, values=(
                    infohash_display,
                    seeders,
                    leechers,
                    total_peers,
                    growth_str,
                    shrink_str,
                    exploding_str,
                    status,
                    last_check
                ))

                self.tree.set(item, "Exploding", f"{exploding_str}")
                
                if total_peers > 0:
                    self.tree.set(item, "Status", "Healthy")
                else:
                    self.tree.set(item, "Status", "No Peers")
            
            self.log(f"Refreshed data: {total} entries, {healthy} healthy, {unhealthy} unhealthy")
            
        except Exception as e:
            self.log(f"Error refreshing data: {e}")
    
    def start_refresh_loop(self):
        def refresh_loop():
            while True:
                time.sleep(30)
                if not self.running.is_set():  # Only refresh if checker is not running
                    try:
                        self.root.after(0, self.refresh_data)
                    except:
                        pass
        
        self.refresh_thread = Thread(target=refresh_loop, daemon=True)
        self.refresh_thread.start()
    
    def toggle_checker(self):
        if not self.running.is_set():
            # Start checker
            self.running.set()
            self.start_button.config(text="Stop Health Checker")
            self.status_label.config(text="Status: Running", foreground="green")
            self.log("Starting health checker...")
            
            def run_checker():
                try:
                    if not self.checker:
                        self.checker = HealthChecker(csv_path=self.csv_path, mode=self.mode)
                        self.checker.initialize()
                    # Run in background
                    def checker_loop():
                        while self.running.is_set():
                            try:
                                health = self.checker.run_once()
                                self.root.after(0, lambda: self.log(
                                    f"Health check: {health['infohash'][:16] if health['infohash'] else 'N/A'} - {health['peers']} peers"
                                ))
                                self.root.after(0, self.refresh_data)
                            except Exception as e:
                                self.root.after(0, lambda: self.log(f"Error in health check: {e}"))
                            
                            if self.running.is_set():
                                time.sleep(5)  # 30 seconds between checks
                    checker_loop()
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"Error starting checker: {e}"))
                    self.running.clear()
                    self.root.after(0, lambda: self.status_label.config(text="Status: Error", foreground="red"))
            
            checker_thread = Thread(target=run_checker, daemon=True)
            checker_thread.start()
        else:
            # Stop checker
            self.running.clear()
            self.start_button.config(text="▶ Start Health Checker")
            self.status_label.config(text="Status: Stopped", foreground="red")
            self.log("Stopped health checker")
    
    def run(self):
        self.root.mainloop()


def run_gui(csv_path: str = "torrents.csv", mode: str = "csv"):
    app = SwarmHealthGUI(csv_path, mode)
    app.run()

