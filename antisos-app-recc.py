import gi
import os
import sys
from typing import Dict, List, Set, Tuple, Any
import json # Added for settings persistence
import threading
import subprocess

# Try to import GTK 4 and Libadwaita
try:
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GLib, Gio
except ImportError:
    print("Error: Required dependencies (GTK 4, Libadwaita, and Python GObject bindings) not found.")
    print("Please ensure 'python-gobject' and 'libadwaita' are installed.")
    exit(1)

# Custom Widget to display an application like an App Store card
class AppCard(Gtk.Box):
    def __init__(self, common_name: str, app_data: Dict[str, Any], resolver_app: Any):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        self.common_name = common_name
        self.app_data = app_data
        self.resolver_app = resolver_app # Reference to the main application for state changes
        
        # Track selected state for the main app
        self.resolver_app.selected_packages[common_name] = False

        self.set_css_classes(['card', 'rounded-lg', 'shadow-md'])
        self.set_size_request(200, 150) # Minimum card size
        
        # FIX: Replaced set_margin_all(8)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        
        container = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        
        # FIX: Replaced container.set_margin_all(15)
        container.set_margin_start(15)
        container.set_margin_end(15)
        container.set_margin_top(15)
        container.set_margin_bottom(15)
        
        # 1. Icon and Title
        header_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        
        icon = Gtk.Image.new_from_icon_name(app_data['icon'])
        icon.set_icon_size(Gtk.IconSize.NORMAL)
        
        # Name and Checkbox on the right
        name_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 2)
        
        title_label = Gtk.Label.new(app_data['name'])
        title_label.set_halign(Gtk.Align.START)
        title_label.set_ellipsize(True)
        title_label.add_css_class('title-4')
        
        self.check_button = Gtk.CheckButton.new()
        self.check_button.set_halign(Gtk.Align.END)
        self.check_button.set_valign(Gtk.Align.CENTER)
        self.check_button.connect('toggled', self.on_toggled)

        name_container = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        name_container.append(title_label)
        name_container.set_hexpand(True)
        name_container.append(self.check_button)

        header_box.append(icon)
        header_box.set_spacing(12)
        header_box.append(name_container)

        # 2. Description
        desc_label = Gtk.Label.new(app_data['desc'])
        desc_label.set_wrap(True)
        desc_label.set_justify(Gtk.Justification.LEFT)
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_max_width_chars(30)
        desc_label.add_css_class('body')
        
        container.append(header_box)
        container.append(desc_label)

        # FIX: Gtk.Box uses append() not set_child()
        self.append(container) 

    def on_toggled(self, check_button):
        """Updates the main application's state when a package is selected."""
        is_selected = check_button.get_active()
        self.resolver_app.selected_packages[self.common_name] = is_selected
        
        if is_selected:
            self.add_css_class('suggested-action') # Highlight selected card
        else:
            self.remove_css_class('suggested-action')


class AppStoreResolver(Adw.Application):
    """
    A Libadwaita application for generating categorized installation commands,
    acting as a simple App Store frontend.
    """
    def __init__(self, **kwargs):
        super().__init__(application_id='io.github.antis.antisos-store', **kwargs)
        self.connect('activate', self.on_activate)

        # Define an "about" action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_action)
        self.add_action(about_action)

        # STATE TRACKING
        self.source_states: Dict[str, bool] = {
            'flatpak': True,
            'snap': False,
            'aur': True,
            'nix': False
        }
        # Tracks which packages the user has checked in the App Store view
        self.selected_packages: Dict[str, bool] = {} 

        # FULL PACKAGE CATALOG
        self.catalog: Dict[str, Dict[str, Any]] = {
            # Browsers
            'brave': {'name': 'Brave', 'icon': 'network-workgroup-symbolic', 'desc': 'Fast, private, secure web browser.', 'map': {'flatpak': 'com.brave.Browser', 'snap': 'brave', 'aur': 'brave-bin', 'nix': 'brave'}, 'category': 'Browsers'},
            'librewolf': {'name': 'LibreWolf', 'icon': 'network-workgroup-symbolic', 'desc': 'Privacy-focused Firefox fork.', 'map': {'flatpak': 'io.gitlab.librewolf-community', 'aur': 'librewolf', 'nix': 'librewolf'}, 'category': 'Browsers'},
            'chrome': {'name': 'Google Chrome', 'icon': 'network-workgroup-symbolic', 'desc': 'Google’s proprietary web browser.', 'map': {'snap': 'google-chrome', 'aur': 'google-chrome', 'nix': 'google-chrome'}, 'category': 'Browsers'},
            'chromium': {'name': 'Chromium', 'icon': 'network-workgroup-symbolic', 'desc': 'Open-source basis for Chrome.', 'map': {'flatpak': 'org.chromium.Chromium', 'snap': 'chromium', 'aur': 'chromium', 'nix': 'chromium'}, 'category': 'Browsers'},
            'ungoogled chromium': {'name': 'Ungoogled Chromium', 'icon': 'network-workgroup-symbolic', 'desc': 'Chromium without Google services.', 'map': {'flatpak': 'com.github.Eloston.UngoogledChromium', 'aur': 'ungoogled-chromium', 'nix': 'ungoogled-chromium'}, 'category': 'Browsers'},
            'zen browser': {'name': 'Zen Browser', 'icon': 'network-workgroup-symbolic', 'desc': 'Focus-oriented web browsing.', 'map': {'aur': 'zen-browser-bin'}, 'category': 'Browsers'},
            'helium browser': {'name': 'Helium Browser', 'icon': 'network-workgroup-symbolic', 'desc': 'Minimalist floating browser.', 'map': {'aur': 'helium-browser-bin'}, 'category': 'Browsers'},
            # Development
            'vscode': {'name': 'VS Code', 'icon': 'document-edit-symbolic', 'desc': 'Microsoft’s popular code editor.', 'map': {'flatpak': 'com.visualstudio.Code', 'snap': 'code', 'aur': 'visual-studio-code-bin', 'nix': 'vscode'}, 'category': 'Development'},
            'vscodium': {'name': 'VSCodium', 'icon': 'document-edit-symbolic', 'desc': 'VS Code without MS telemetry.', 'map': {'flatpak': 'com.vscodium.codium', 'aur': 'vscodium-bin', 'nix': 'vscodium'}, 'category': 'Development'},
            # Office
            'libreoffice': {'name': 'LibreOffice', 'icon': 'document-edit-symbolic', 'desc': 'The powerful, free office suite.', 'map': {'flatpak': 'org.libreoffice.LibreOffice', 'snap': 'libreoffice', 'aur': 'libreoffice-fresh', 'nix': 'libreoffice'}, 'category': 'Office'},
            'onlyoffice': {'name': 'OnlyOffice', 'icon': 'document-edit-symbolic', 'desc': 'Alternative office suite.', 'map': {'flatpak': 'org.onlyoffice.desktopeditors', 'snap': 'onlyoffice-desktopeditors', 'aur': 'onlyoffice-bin'}, 'category': 'Office'},
            # Utilities
            '1password': {'name': '1Password', 'icon': 'dialog-password-symbolic', 'desc': 'Secure password management.', 'map': {'snap': '1password', 'aur': '1password', 'nix': 'onepassword'}, 'category': 'Utilities'},
            'keepassxc': {'name': 'KeePassXC', 'icon': 'dialog-password-symbolic', 'desc': 'Free, cross-platform password manager.', 'map': {'flatpak': 'org.keepassxc.KeePassXC', 'snap': 'keepassxc', 'aur': 'keepassxc', 'nix': 'keepassxc'}, 'category': 'Utilities'},
            'redshift': {'name': 'Redshift', 'icon': 'weather-clear-night-symbolic', 'desc': 'Adjusts screen temperature.', 'map': {'flatpak': 'org.geoclue.Redshift', 'snap': 'redshift', 'aur': 'redshift', 'nix': 'redshift'}, 'category': 'Utilities'},
            'timeshift': {'name': 'Timeshift', 'icon': 'document-revert-symbolic', 'desc': 'System restore utility for Linux.', 'map': {'aur': 'timeshift', 'nix': 'timeshift'}, 'category': 'Utilities'},
            'tty-clock': {'name': 'TTY-Clock', 'icon': 'utilities-terminal-symbolic', 'desc': 'A simple clock for the terminal.', 'map': {'aur': 'tty-clock', 'nix': 'tty-clock'}, 'category': 'Utilities'},
            'ms-fonts': {'name': 'MS Fonts', 'icon': 'font-x-generic-symbolic', 'desc': 'Microsoft TrueType core fonts.', 'map': {'aur': 'ttf-ms-fonts'}, 'category': 'Utilities'},
            'snapd': {'name': 'Snapd', 'icon': 'system-software-install-symbolic', 'desc': 'The service for running Snap packages.', 'map': {'aur': 'snapd'}, 'category': 'Utilities'},
            # Gaming
            'steam': {'name': 'Steam', 'icon': 'applications-games-symbolic', 'desc': 'Valve\'s digital distribution service.', 'map': {'flatpak': 'com.valvesoftware.Steam', 'snap': 'steam', 'aur': 'steam', 'nix': 'steam'}, 'category': 'Gaming'},
            'lutris': {'name': 'Lutris', 'icon': 'applications-games-symbolic', 'desc': 'Open Gaming Platform for Linux.', 'map': {'flatpak': 'net.lutris.Lutris', 'snap': 'lutris', 'aur': 'lutris', 'nix': 'lutris'}, 'category': 'Gaming'},
            'proton-ge': {'name': 'Proton-GE', 'icon': 'applications-games-symbolic', 'desc': 'Custom Proton build for Steam/Lutris.', 'map': {'aur': 'proton-ge-custom-bin'}, 'category': 'Gaming'},
            # Graphics & Multimedia
            'gimp': {'name': 'GIMP', 'icon': 'applications-graphics-symbolic', 'desc': 'GNU Image Manipulation Program.', 'map': {'flatpak': 'org.gimp.GIMP', 'snap': 'gimp', 'aur': 'gimp', 'nix': 'gimp'}, 'category': 'Graphics & Multimedia'},
            'krita': {'name': 'Krita', 'icon': 'applications-graphics-symbolic', 'desc': 'Professional painting program.', 'map': {'flatpak': 'org.kde.krita', 'snap': 'krita', 'aur': 'krita', 'nix': 'krita'}, 'category': 'Graphics & Multimedia'},
            'kdenlive': {'name': 'Kdenlive', 'icon': 'applications-multimedia-symbolic', 'desc': 'Free video editing software.', 'map': {'flatpak': 'org.kde.kdenlive', 'snap': 'kdenlive', 'aur': 'kdenlive', 'nix': 'kdenlive'}, 'category': 'Graphics & Multimedia'},
            'spotify': {'name': 'Spotify', 'icon': 'applications-multimedia-symbolic', 'desc': 'Digital music streaming service.', 'map': {'flatpak': 'com.spotify.Client', 'snap': 'spotify', 'aur': 'spotify', 'nix': 'spotify'}, 'category': 'Graphics & Multimedia'},
            'zoom': {'name': 'Zoom', 'icon': 'camera-web-symbolic', 'desc': 'Video conferencing tool.', 'map': {'flatpak': 'us.zoom.Zoom', 'snap': 'zoom-client', 'aur': 'zoom', 'nix': 'zoom'}, 'category': 'Graphics & Multimedia'},
            # System & Virtualization
            'bottles': {'name': 'Bottles', 'icon': 'applications-other-symbolic', 'desc': 'Manage Windows environments.', 'map': {'flatpak': 'com.usebottles.bottles', 'aur': 'bottles', 'nix': 'bottles'}, 'category': 'System & Virtualization'},
            'wine': {'name': 'Wine', 'icon': 'applications-other-symbolic', 'desc': 'Run Windows applications.', 'map': {'flatpak': 'org.winehq.Wine', 'aur': 'wine', 'nix': 'wine'}, 'category': 'System & Virtualization'},
            'gearlever': {'name': 'Gear Lever', 'icon': 'application-x-executable-symbolic', 'desc': 'Manage AppImages.', 'map': {'flatpak': 'it.mijorus.gearlever'}, 'category': 'System & Virtualization'},
            'appimagelauncher': {'name': 'AppImageLauncher', 'icon': 'application-x-executable-symbolic', 'desc': 'Integrate AppImages into your system.', 'map': {'aur': 'appimagelauncher'}, 'category': 'System & Virtualization'},
            'boxbuddy': {'name': 'BoxBuddy', 'icon': 'utilities-terminal-symbolic', 'desc': 'GUI for Toolbx/Distrobox containers.', 'map': {'flatpak': 'com.github.flxzt.boxbuddy'}, 'category': 'System & Virtualization'},
            # Social
            'goofcord': {'name': 'Goofcord', 'icon': 'system-users-symbolic', 'desc': 'Discord client alternative.', 'map': {'aur': 'goofcord-bin'}, 'category': 'Social'},
            'vesktop': {'name': 'Vesktop', 'icon': 'system-users-symbolic', 'desc': 'Custom Discord client with Vencord.', 'map': {'aur': 'vesktop-bin'}, 'category': 'Social'},
        }

        # Settings file path
        self.settings_dir = os.path.join(GLib.get_user_config_dir(), 'antisos-store')
        self.settings_file = os.path.join(self.settings_dir, 'settings.json')
        self.is_first_launch = not os.path.exists(self.settings_file)
        self.load_settings()

    def load_settings(self):
        """Loads source and package selections from the settings file."""
        if self.is_first_launch:
            return # Don't load settings if it's the first launch
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    # Use .get() to avoid errors if keys are missing in the file
                    self.source_states = settings.get('sources', self.source_states)
                    self.selected_packages = settings.get('packages', self.selected_packages)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load settings from {self.settings_file}. Using defaults. Error: {e}")

    def save_settings(self, *args):
        """Saves the current source and package selections to the settings file."""
        settings = {
            'sources': self.source_states,
            'packages': self.selected_packages
        }
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except IOError as e:
            print(f"Error: Could not save settings to {self.settings_file}. Error: {e}")

    def on_source_toggled(self, switch: Gtk.Switch, pspec, source: str):
        """Updates the internal state when a source switch is toggled."""
        self.source_states[source] = switch.get_active()

    def on_activate(self, app):
        """Called when the application is activated."""
        self.create_window()

    def create_window(self):
        """Builds the main Libadwaita application window."""
        self.window = Adw.ApplicationWindow.new(self)
        self.window.set_default_size(900, 700)
        self.window.set_title("antisOS store")
        
        # --- Header Bar ---
        header_bar = Adw.HeaderBar.new()
        header_bar.set_title_widget(Adw.WindowTitle.new("antisOS store", "Select apps, generate script"))

        # --- Menu Button for "About" ---
        menu = Gio.Menu.new()
        menu.append("About antisOS store", "app.about")

        menu_button = Gtk.MenuButton.new()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        header_bar.pack_end(menu_button)
        
        # --- View Stack (Config, App Store, Output) ---
        self.view_stack = Adw.ViewStack.new()

        # 0. Welcome Page (only shown on first launch)
        if self.is_first_launch:
            welcome_page = self._create_welcome_page()
            self.view_stack.add_named(welcome_page, "welcome")

        # 1. Source Configuration Page (Preferences style)
        config_page = self._create_config_page()
        self.view_stack.add_titled_with_icon(config_page, "config", "Sources", "system-software-install-symbolic")

        # 2. App Store Selection Page (Grid style)
        app_store_page = self._create_app_store_page()
        self.view_stack.add_titled_with_icon(app_store_page, "selection", "Selection", "view-grid-symbolic")
        
        # 3. Output Page
        output_page = self._create_output_page()
        self.view_stack.add_titled_with_icon(output_page, "output", "Results", "document-save-symbolic")

        # --- View Switcher (Replaces ViewStackSidebar for Adw.ViewStack) ---
        view_switcher = Adw.ViewSwitcher.new()
        view_switcher.set_stack(self.view_stack)

        # --- Main Layout ---
        content = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        content.append(header_bar)
        content.append(view_switcher)
        content.append(self.view_stack)

        # Make the view_stack expand to fill available space
        self.view_stack.set_vexpand(True)

        # Set the initial visible page
        if self.is_first_launch:
            self.view_stack.set_visible_child_name("welcome")
            header_bar.set_visible(False) # Hide header on welcome screen

        self.window.set_content(content)
        self.window.present()

    def _create_config_page(self) -> Gtk.Widget:
        """Creates the source configuration view (GNOME Preferences look)."""
        page = Adw.PreferencesPage.new()

        # --- Group 1: Installation Sources (Toggles) ---
        group_sources = Adw.PreferencesGroup.new()
        group_sources.set_title("Installation Sources")
        group_sources.set_description("Enable the package systems available on your machine. Priority is Flatpak > Snap > AUR > Nix.")

        # Flatpak
        flatpak_row = Adw.SwitchRow.new()
        flatpak_row.set_title("Flatpak (Recommended)")
        flatpak_row.set_subtitle("Universal Linux packaging via Flathub.")
        flatpak_row.set_active(self.source_states['flatpak'])
        flatpak_row.connect('notify::active', self.on_source_toggled, 'flatpak')
        group_sources.add(flatpak_row)
        
        # Snap
        snap_row = Adw.SwitchRow.new()
        snap_row.set_title("Snap")
        snap_row.set_subtitle("Canonical's package system.")
        snap_row.set_active(self.source_states['snap'])
        snap_row.connect('notify::active', self.on_source_toggled, 'snap')
        group_sources.add(snap_row)

        # AUR/Pacman
        aur_row = Adw.SwitchRow.new()
        aur_row.set_title("AUR / Pacman (Arch)")
        aur_row.set_subtitle("Requires Paru or Yay for AUR packages.")
        aur_row.set_active(self.source_states['aur'])
        aur_row.connect('notify::active', self.on_source_toggled, 'aur')
        group_sources.add(aur_row)

        # Nix
        nix_row = Adw.SwitchRow.new()
        nix_row.set_title("Nix")
        nix_row.set_subtitle("Installs packages via the Nix package manager.")
        nix_row.set_active(self.source_states['nix'])
        nix_row.connect('notify::active', self.on_source_toggled, 'nix')
        group_sources.add(nix_row)

        page.add(group_sources)
        
        # --- Action Button (Must be inside an Adw.PreferencesGroup) ---
        generate_button = Gtk.Button.new_with_label("Go to Package Selection")
        generate_button.add_css_class('pill')
        generate_button.add_css_class('suggested-action')
        generate_button.connect('clicked', lambda *args: self.view_stack.set_visible_child_name("selection"))
        
        action_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        action_box.set_halign(Gtk.Align.END)
        action_box.set_margin_top(20)
        action_box.set_margin_end(24)
        action_box.append(generate_button)
        
        # FIX: Wrap action_box in a PreferencesGroup before adding to the Page
        group_actions = Adw.PreferencesGroup.new()
        group_actions.add(action_box)
        page.add(group_actions)

        return page

    def _create_welcome_page(self) -> Gtk.Widget:
        """Creates the welcome page shown on first launch."""
        page = Adw.StatusPage.new()
        page.set_icon_name("system-software-install-symbolic")
        page.set_title("Welcome to the antisOS store")
        page.set_description(
            "This tool helps you generate a single installation script for applications "
            "from different package sources like Flatpak, Snap, and the AUR.\n\n"
            "Get started by configuring your preferred sources."
        )

        get_started_button = Gtk.Button.new_with_label("Get Started")
        get_started_button.add_css_class("suggested-action")
        get_started_button.add_css_class("pill")
        get_started_button.connect("clicked", self.on_get_started_clicked)
        page.set_child(get_started_button)

        return page

    def on_get_started_clicked(self, button):
        """Handles the 'Get Started' button on the welcome page."""
        self.window.get_content().get_first_child().set_visible(True) # Show header bar
        self.view_stack.set_visible_child_name("config")
        self.save_settings() # Create the settings file to mark first launch as complete

    def _create_app_store_page(self) -> Gtk.Widget:
        """Creates the app store-style selection view."""
        page = Adw.PreferencesPage.new()
        self.app_cards = [] # To hold all AppCard widgets for easy iteration
        self.category_groups = {} # To hold category groups for filtering

        # Group apps by category
        apps_by_category = {}
        for key, data in self.catalog.items():
            category = data.get('category', 'Other')
            if category not in apps_by_category:
                apps_by_category[category] = []
            apps_by_category[category].append((key, data))

        # Create a group for each category
        for category_name in sorted(apps_by_category.keys()):
            group = Adw.PreferencesGroup.new()
            group.set_title(category_name)
            
            flow_box = Gtk.FlowBox.new()
            flow_box.set_homogeneous(False)
            flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
            flow_box.set_valign(Gtk.Align.START)
            flow_box.set_max_children_per_line(5)
            flow_box.set_column_spacing(10)
            flow_box.set_row_spacing(10)

            for key, data in sorted(apps_by_category[category_name], key=lambda item: item[1]['name']):
                card = AppCard(key, data, self)
                # Set the initial state of the checkbox from loaded settings
                if self.selected_packages.get(key, False):
                    card.check_button.set_active(True)
                self.app_cards.append(card)
                flow_box.append(card)
            
            group.add(flow_box)
            page.add(group)
            self.category_groups[category_name] = group

        # Scrollable container
        scrolled_window = Gtk.ScrolledWindow.new()
        scrolled_window.set_child(page)
        scrolled_window.set_vexpand(True) # The main view_stack is now the expanding child

        # Box to hold FlowBox and Generate Button
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)

        # --- Search and Select All Bar ---
        search_bar_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        search_bar_box.set_margin_start(20)
        search_bar_box.set_margin_end(20)
        search_bar_box.set_margin_top(10)

        search_entry = Gtk.SearchEntry.new()
        search_entry.set_placeholder_text("Search for apps...")
        search_entry.set_hexpand(True)
        search_entry.connect("search-changed", self.on_search_changed)
        search_bar_box.append(search_entry)

        # Select All CheckButton
        select_all_button = Gtk.CheckButton.new_with_label("Select All")
        select_all_button.set_tooltip_text("Select/Deselect all visible apps")
        select_all_button.connect("toggled", self.on_select_all_toggled)
        search_bar_box.append(select_all_button)

        box.append(search_bar_box)
        box.append(scrolled_window)

        # Generate Button
        generate_button = Gtk.Button.new_with_label("Generate Installation Plan")
        generate_button.add_css_class('pill')
        generate_button.add_css_class('suggested-action')
        generate_button.connect('clicked', self.on_generate_clicked)

        action_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        action_box.set_halign(Gtk.Align.CENTER)
        action_box.set_margin_bottom(20)
        action_box.append(generate_button)
        box.append(action_box)

        return box

    def on_select_all_toggled(self, button: Gtk.CheckButton):
        """Selects or deselects all currently visible app cards."""
        is_active = button.get_active()

        for app_card in self.app_cards:
            # Only affect cards that are currently visible (respects search filter)
            if app_card.get_visible():
                # Set the card's check button state, which triggers its own 'toggled' signal
                app_card.check_button.set_active(is_active)

    def on_search_changed(self, search_entry: Gtk.SearchEntry):
        """Filters the app grid based on the search query."""
        query = search_entry.get_text().lower().strip()

        # Keep track of which categories have visible apps
        visible_categories = set()

        # First, filter the individual app cards
        for app_card in self.app_cards:
            app_name = app_card.app_data['name'].lower()
            app_desc = app_card.app_data['desc'].lower()
            is_visible = query in app_name or query in app_desc
            app_card.set_visible(is_visible)
            if is_visible:
                visible_categories.add(app_card.app_data.get('category', 'Other'))

        # Second, filter the category groups
        for category_name, group in self.category_groups.items():
            group.set_visible(category_name in visible_categories)

    def on_about_action(self, action, param):
        """Shows the About dialog."""
        about = Adw.AboutWindow.new()
        about.set_transient_for(self.window)
        about.set_application_name("antisOS store")
        about.set_application_icon("system-software-install-symbolic")
        about.set_version("1.0.0")
        about.set_developer_name("antis")
        about.set_website("https://github.com/antis-build")
        about.set_comments("A simple tool to select applications and generate a unified installation script for multiple package managers.")
        about.set_license_type(Gtk.License.MIT_X11)
        about.add_credit_section("Created with", ["Python", "GTK 4", "Libadwaita"])
        
        # Add a link to the source code
        about.add_link("Source Code on GitHub", "https://github.com/")
        
        about.present()


    def _create_output_page(self) -> Gtk.Widget:
        """Creates the output view to display the generated commands."""
        
        # Output Text View
        self.output_buffer = Gtk.TextBuffer.new()
        self.output_text_view = Gtk.TextView.new_with_buffer(self.output_buffer)
        self.output_text_view.set_monospace(True)
        self.output_text_view.set_editable(False)
        self.output_text_view.set_wrap_mode(Gtk.WrapMode.WORD)

        output_scroll = Gtk.ScrolledWindow.new()
        output_scroll.set_child(self.output_text_view)
        output_scroll.set_size_request(400, 500)
        
        # FIX: Replaced set_margin_all(24)
        output_scroll.set_margin_start(24)
        output_scroll.set_margin_end(24)
        output_scroll.set_margin_top(24)
        output_scroll.set_margin_bottom(24)

        # --- Action Buttons ---
        # Copy Button
        self.copy_button = Gtk.Button.new_with_label("Copy to Clipboard")
        self.copy_button.add_css_class('pill')
        self.copy_button.connect('clicked', self.on_copy_clicked)

        # Install Button
        self.install_button = Gtk.Button.new_with_label("Install All")
        self.install_button.add_css_class('suggested-action')
        self.install_button.add_css_class('pill')
        self.install_button.connect('clicked', self.on_install_clicked)

        # Cancel Button
        self.cancel_button = Gtk.Button.new_with_label("Cancel")
        self.cancel_button.add_css_class('destructive-action')
        self.cancel_button.add_css_class('pill')
        self.cancel_button.connect('clicked', self.on_cancel_clicked)

        # Installation Spinner
        self.install_spinner = Gtk.Spinner.new()

        # Status Page container
        self.status_page = Adw.StatusPage.new()
        self.status_page.set_icon_name("document-save-symbolic")
        self.status_page.set_title("Plan Not Generated")
        
        # Layout (Wrap TextView and Button inside a container)
        container = Gtk.Box.new(Gtk.Orientation.VERTICAL, 18)
        container.set_vexpand(True)
        container.set_valign(Gtk.Align.FILL)
        container.append(output_scroll)
        
        button_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_bottom(20)
        button_box.append(self.install_spinner)
        button_box.append(self.copy_button)
        button_box.append(self.install_button)
        button_box.append(self.cancel_button)
        
        container.append(button_box)
        self.status_page.set_description("Select your apps and click 'Generate Installation Plan' to see the script.")
        self.status_page.set_child(container)
        
        return self.status_page

    def on_copy_clicked(self, button):
        """Copies the generated script to the system clipboard."""
        clipboard = Gtk.Clipboard.get_default_for_display(self.window.get_display())
        if clipboard:
            start, end = self.output_buffer.get_bounds()
            text = self.output_buffer.get_text(start, end, False)
            clipboard.set_text(text, -1)
            
            # Temporary UI feedback
            original_label = self.copy_button.get_label()
            self.copy_button.set_label("Copied!")
            GLib.timeout_add_seconds(1, lambda: self.copy_button.set_label(original_label) or False)

    def generate_commands(self) -> str:
        """Generates the structured command list based on source toggles and selected packages."""
        
        # Commands grouped by source
        commands: Dict[str, Set[str]] = {
            'Flatpak': set(),
            'Snap': set(),
            'AUR/Pacman (Paru)': set(),
            'Nix': set(),
            'Unresolved': set()
        }
        
        # Command definitions
        flatpak_cmd = "flatpak install flathub -y "
        snap_cmd = "snap install " # pkexec will handle sudo
        aur_cmd = "paru -S --needed --noconfirm "
        nix_cmd_start = "nix-env -iA "
        nix_cmd_pkg_prefix = "nixpkgs."
        
        # Get only the packages the user selected
        selected_app_keys = [
            key for key, is_selected in self.selected_packages.items() 
            if is_selected
        ]
        
        if not selected_app_keys:
            return "# Error: No packages were selected. Please select one or more apps from the Selection tab."

        # Track packages that have been successfully mapped to enforce priority
        mapped_packages: Set[str] = set()

        for key in selected_app_keys:
            pkg_data = self.catalog.get(key, {})
            pkg_map = pkg_data.get('map', {})
            
            installed = False

            # Priority 1: Flatpak
            if self.source_states['flatpak'] and pkg_map.get('flatpak') and key not in mapped_packages:
                commands['Flatpak'].add(pkg_map['flatpak'])
                mapped_packages.add(key)
                installed = True
            
            # Priority 2: Snap
            if not installed and self.source_states['snap'] and pkg_map.get('snap') and key not in mapped_packages:
                commands['Snap'].add(pkg_map['snap'])
                mapped_packages.add(key)
                installed = True

            # Priority 3: AUR/Pacman
            if not installed and self.source_states['aur'] and pkg_map.get('aur') and key not in mapped_packages:
                commands['AUR/Pacman (Paru)'].add(pkg_map['aur'])
                mapped_packages.add(key)
                installed = True
                
            # Priority 4: Nix
            if not installed and self.source_states['nix'] and pkg_map.get('nix') and key not in mapped_packages:
                commands['Nix'].add(pkg_map['nix'])
                mapped_packages.add(key)
                installed = True

            if not installed:
                 commands['Unresolved'].add(pkg_data.get('name', key))

        # --- Format Output ---
        output_parts: List[str] = []
        
        output_parts.append("#!/bin/bash")
        output_parts.append("set -e # Exit immediately if a command exits with a non-zero status.")
        output_parts.append("")
        output_parts.append("# --- Installation Script Generated by antisOS store ---")
        output_parts.append("# Enabled Sources (Priority: Flatpak > Snap > AUR > Nix):")
        output_parts.append(f"# Flatpak: {'Enabled' if self.source_states['flatpak'] else 'Disabled'}")
        output_parts.append(f"# Snap:    {'Enabled' if self.source_states['snap'] else 'Disabled'}")
        output_parts.append(f"# AUR:     {'Enabled' if self.source_states['aur'] else 'Disabled'}")
        output_parts.append(f"# Nix:     {'Enabled' if self.source_states['nix'] else 'Disabled'}")
        output_parts.append("# ----------------------------------------------------------\n")

        for source in ['Flatpak', 'Snap', 'AUR/Pacman (Paru)', 'Nix', 'Unresolved']:
            pkg_set = commands.get(source, set())
            if not pkg_set:
                continue

            output_parts.append(f"# ## {source} Packages ({len(pkg_set)})")
            output_parts.append("# ----------------------------------------------------------")
            
            if source == 'Flatpak':
                output_parts.append(f"{flatpak_cmd} {' '.join(sorted(pkg_set))}")
            elif source == 'Snap':
                output_parts.append(f"sudo {snap_cmd} {' '.join(sorted(pkg_set))}")
            elif source == 'AUR/Pacman (Paru)':
                output_parts.append(f"{aur_cmd} {' '.join(sorted(pkg_set))}")
            elif source == 'Nix':
                nix_packages = [f'{nix_cmd_pkg_prefix}{p}' for p in sorted(pkg_set)]
                output_parts.append(f"{nix_cmd_start} {' '.join(nix_packages)}")
            elif source == 'Unresolved':
                output_parts.append(f"# WARNING: The following selected packages could not be mapped to any enabled source:")
                output_parts.append(f"# {', '.join(sorted(pkg_set))}")

            output_parts.append("\n")

        return '\n'.join(output_parts)

    def on_generate_clicked(self, button):
        """Generates the script and switches to the output view."""
        
        generated_script = self.generate_commands()
        self.output_buffer.set_text(generated_script)
        
        # Update the status page description
        selected_count = sum(self.selected_packages.values())
        if selected_count > 0:
            self.status_page.set_title(f"{selected_count} Apps Ready to Install")
            self.status_page.set_description(
                "Copy the commands below and paste them into your terminal. "
                "Run them one block at a time to install all your selected apps."
            )
        else:
            self.status_page.set_title("No Apps Selected")
            self.status_page.set_description("Please go back to the Selection tab and choose the packages you want to install.")
            
        # Switch to the output tab
        self.view_stack.set_visible_child_name("output")

    def on_install_clicked(self, button):
        """Handles the 'Install' button click to execute commands."""
        script_content = self.generate_commands()

        # Don't run if no packages were selected
        if "Error: No packages were selected" in script_content:
            self.output_buffer.set_text(script_content)
            return
        self.cancel_requested = False

        # Start the installation in a separate thread
        install_thread = threading.Thread(target=self.run_installation, args=(script_content,))
        install_thread.start()

    def run_installation(self, script_content: str):
        """Worker function to run the installation script in a background thread."""
        # --- Prepare UI for installation (must run on main thread) ---
        GLib.idle_add(self.prepare_ui_for_install)

        # --- Execute Script ---
        try:
            # Create a temporary script file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sh', prefix='app-resolver-') as f:
                f.write(script_content)
                script_path = f.name
            
            os.chmod(script_path, 0o755) # Make it executable

            # Use pkexec to run the script with elevated privileges
            # This will prompt the user for their password via a system dialog
            self.install_process = subprocess.Popen(
                ['pkexec', '/bin/bash', script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Redirect stderr to stdout
                text=True,
                bufsize=1, # Line-buffered
            )

            # Stream output to the TextView
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    # Schedule UI update on the main thread
                    GLib.idle_add(self.append_output, line)
            
            self.install_process.wait()
            
            # Determine final status
            if self.cancel_requested:
                status = "CANCELLED"
            elif self.install_process.returncode == 0:
                status = "COMPLETE"
            else:
                status = "FAILED"

        except Exception as e:
            GLib.idle_add(self.append_output, f"\n--- FATAL ERROR ---\n{e}\n")
            status = "FAILED"
        finally:
            # --- Finalize UI (must run on main thread) ---
            GLib.idle_add(self.finalize_ui_after_install, status)
            if 'script_path' in locals() and os.path.exists(script_path):
                os.remove(script_path) # Clean up the temporary script
            self.install_process = None

    def on_cancel_clicked(self, button):
        """Handles the 'Cancel' button click."""
        self.cancel_requested = True
        if self.install_process and self.install_process.poll() is None:
            # The process is still running, terminate it.
            # Since we used pkexec, killing the parent pkexec process
            # should also terminate the child script.
            self.install_process.terminate()
            GLib.idle_add(self.append_output, "\n\n--- CANCELLATION REQUESTED ---\nTerminating process...\n")

    def prepare_ui_for_install(self):
        self.output_buffer.set_text("Starting installation...\nThis may take a while. Please enter your password when prompted.\n\n")
        self.install_spinner.start()
        self.install_button.set_visible(False)
        self.copy_button.set_visible(False)
        self.cancel_button.set_visible(True)

    def append_output(self, text: str):
        self.output_buffer.insert_at_cursor(text)

    def finalize_ui_after_install(self, status: str):
        """Restores the UI to its idle state after installation finishes."""
        self.install_spinner.stop()
        self.install_button.set_visible(True)
        self.copy_button.set_visible(True)
        self.cancel_button.set_visible(False)
        self.append_output(f"\n--- INSTALLATION {status} ---\n")

if __name__ == '__main__':
    # Set the application name for display in the shell
    os.environ['GIO_APPLICATION_NAME'] = "antisOS store"
    app = AppStoreResolver()
    app.run(sys.argv)