#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 BOYKA - OTO ÇEKME YAZILIMI
Telegram Otomatik Üye Çekme Uygulaması

Geliştirici: @yamacbey7
Sürüm: 1.0.0
"""

import sys
import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QTextEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QProgressBar,
    QSpinBox, QComboBox, QFileDialog, QDialog, QFormLayout
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# ==================== KONFİGURASYON ====================

class Config:
    """Uygulama Konfigürasyonu"""
    # Telegram API (BU ALANLARI DOLDURUN)
    API_ID = 0  # https://my.telegram.org/ adresinden alın
    API_HASH = ""  # https://my.telegram.org/ adresinden alın
    
    # Veritabanı
    DB_PATH = "data/boyka.db"
    SESSION_DIR = "sessions"
    
    # Çekme Ayarları
    DELAY_BETWEEN_ADDS = 2  # Saniye
    RETRY_COUNT = 3
    RETRY_DELAY = 300
    ACTIVE_DAYS = 7
    
    # UI Ayarları
    APP_NAME = "BOYKA - OTO ÇEKME YAZILIMI"
    APP_VERSION = "1.0.0"
    WINDOW_WIDTH = 1100
    WINDOW_HEIGHT = 800
    
    # Renkler (Dark Theme)
    COLOR_PRIMARY = "#1e1e1e"
    COLOR_SECONDARY = "#2d2d2d"
    COLOR_ACCENT = "#00bfff"
    COLOR_SUCCESS = "#00ff00"
    COLOR_ERROR = "#ff0000"
    COLOR_WARNING = "#ffff00"

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/boyka.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== VERİTABANI ====================

class DatabaseManager:
    """SQLite Veritabanı Yöneticisi"""
    
    def __init__(self):
        Path("data").mkdir(exist_ok=True)
        self.db_path = Config.DB_PATH
        self.init_database()
    
    def init_database(self):
        """Veritabanını başlat"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Kullanıcılar tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    is_bot BOOLEAN,
                    scraped_date TIMESTAMP
                )
            """)
            
            # İşlemler tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY,
                    operation_id TEXT UNIQUE,
                    source_group TEXT,
                    target_group TEXT,
                    total_members INTEGER,
                    successful INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    status TEXT
                )
            """)
            
            # Sonuçlar tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY,
                    operation_id TEXT,
                    user_id INTEGER,
                    username TEXT,
                    status TEXT,
                    attempt_count INTEGER,
                    last_attempt TIMESTAMP,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                )
            """)
            
            conn.commit()
            conn.close()
            logger.info("✅ Veritabanı başlatıldı")
        except Exception as e:
            logger.error(f"❌ Veritabanı hatası: {e}")
    
    def add_user(self, user_id: int, username: str, first_name: str, is_bot: bool = False):
        """Kullanıcı ekle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, is_bot, scraped_date)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, first_name, is_bot, datetime.now()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ Kullanıcı ekleme hatası: {e}")
    
    def get_all_users(self):
        """Tüm kullanıcıları al"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            conn.close()
            return users
        except Exception as e:
            logger.error(f"❌ Kullanıcı getirme hatası: {e}")
            return []
    
    def add_operation(self, operation_id: str, source_group: str, target_group: str, total_members: int):
        """İşlem ekle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO operations 
                (operation_id, source_group, target_group, total_members, successful, failed, start_time, status)
                VALUES (?, ?, ?, ?, 0, 0, ?, 'RUNNING')
            """, (operation_id, source_group, target_group, total_members, datetime.now()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ İşlem ekleme hatası: {e}")
    
    def update_operation_result(self, operation_id: str, successful: int, failed: int):
        """İşlem sonucunu güncelle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE operations 
                SET successful = ?, failed = ?, end_time = ?, status = 'COMPLETED'
                WHERE operation_id = ?
            """, (successful, failed, datetime.now(), operation_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ İşlem güncelleme hatası: {e}")

# ==================== TELEGRAM İŞLEMLERİ ====================

class TelegramWorker(QThread):
    """Telegram işlemleri için thread"""
    
    auth_code_requested = pyqtSignal()
    auth_2fa_requested = pyqtSignal()
    auth_success = pyqtSignal()
    auth_error = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.client = None
        self.phone = None
    
    def set_phone(self, phone: str):
        self.phone = phone
    
    def run(self):
        """Doğrulama işlemi"""
        try:
            if not Config.API_ID or not Config.API_HASH:
                self.auth_error.emit("❌ API_ID ve API_HASH boş! config.py dosyasını kontrol edin.")
                return
            
            Path(Config.SESSION_DIR).mkdir(exist_ok=True)
            session_name = f"{Config.SESSION_DIR}/{self.phone.replace('+', '').replace(' ', '')}"
            
            self.client = TelegramClient(session_name, Config.API_ID, Config.API_HASH)
            
            # Async işlem
            asyncio.run(self._authenticate())
        except Exception as e:
            self.auth_error.emit(f"❌ Doğrulama hatası: {str(e)}")
    
    async def _authenticate(self):
        """Async doğrulama"""
        try:
            await self.client.connect()
            await self.client.send_code_request(self.phone)
            self.auth_code_requested.emit()
        except Exception as e:
            self.auth_error.emit(f"❌ Doğrulama hatası: {str(e)}")

# ==================== ANA ARAYÜZ ====================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(Config.APP_NAME)
        self.setGeometry(100, 100, Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)
        self.setStyleSheet(self.get_dark_stylesheet())
        
        self.db = DatabaseManager()
        self.client = None
        self.is_authenticated = False
        self.scraping_active = False
        
        # Gerekli klasörleri oluştur
        Path("logs").mkdir(exist_ok=True)
        Path("data").mkdir(exist_ok=True)
        Path("sessions").mkdir(exist_ok=True)
        
        self.init_ui()
        logger.info("🚀 BOYKA uygulaması başlatıldı")
    
    def init_ui(self):
        """Ana arayüzü başlat"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Başlık
        title = QLabel("🚀 BOYKA - OTO ÇEKME YAZILIMI")
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {Config.COLOR_ACCENT}; font-weight: bold;")
        main_layout.addWidget(title)
        
        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {Config.COLOR_SECONDARY};
                color: white;
                padding: 10px 20px;
                border-bottom: 3px solid transparent;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                border-bottom: 3px solid {Config.COLOR_ACCENT};
                background-color: {Config.COLOR_PRIMARY};
            }}
            QTabWidget::pane {{
                border: 2px solid {Config.COLOR_ACCENT};
            }}
        """)
        
        # Sekmeleri oluştur
        self.create_auth_tab()
        self.create_settings_tab()
        self.create_scraper_tab()
        self.create_stats_tab()
        self.create_logs_tab()
        
        main_layout.addWidget(self.tabs)
        
        # Status bar
        self.statusBar().setStyleSheet(f"background-color: {Config.COLOR_SECONDARY}; color: white;")
        self.statusBar().showMessage("✅ Hazır")
    
    def create_auth_tab(self):
        """Doğrulama sekmesi"""
        auth_widget = QWidget()
        layout = QVBoxLayout(auth_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # API Bilgileri
        info_label = QLabel("📋 API Bilgileri")
        info_label.setStyleSheet(f"color: {Config.COLOR_WARNING}; font-weight: bold; font-size: 12px;")
        layout.addWidget(info_label)
        
        api_text = QTextEdit()
        api_text.setReadOnly(True)
        api_text.setMaximumHeight(100)
        api_text.setText("""
🔐 API Bilgilerini https://my.telegram.org/ adresinden alın:

1. my.telegram.org adresine gidin
2. "API Development tools" kısmında
3. "Create new application" yapın
4. API_ID ve API_HASH'i kopyalayın
5. boyka.py dosyasında Config sınıfında güncelleyin
        """)
        api_text.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(api_text)
        
        layout.addWidget(QLabel("-" * 50))
        
        # Telefon Numarası
        layout.addWidget(QLabel("📱 Telegram Numarası"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+90 (555) 123-4567")
        self.phone_input.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(self.phone_input)
        
        # SMS Kodu
        layout.addWidget(QLabel("📨 SMS Kodu"))
        self.sms_input = QLineEdit()
        self.sms_input.setPlaceholderText("SMS'de gelen 5 haneli kodu girin")
        self.sms_input.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(self.sms_input)
        
        # 2FA Kodu
        layout.addWidget(QLabel("🔐 2FA Kodu (Varsa)"))
        self.fa2_input = QLineEdit()
        self.fa2_input.setPlaceholderText("2FA aktifse kodu girin")
        self.fa2_input.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(self.fa2_input)
        
        # Durumu Göster
        self.auth_status = QLabel("❌ Bağlı Değil")
        self.auth_status.setStyleSheet(f"color: {Config.COLOR_ERROR}; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.auth_status)
        
        # Doğrula Butonu
        auth_btn = QPushButton("✅ DOĞRULA VE BAĞLAN")
        auth_btn.setStyleSheet(self.get_button_stylesheet())
        auth_btn.clicked.connect(self.authenticate)
        layout.addWidget(auth_btn)
        
        layout.addStretch()
        self.tabs.addTab(auth_widget, "🔑 Doğrulama")
    
    def create_settings_tab(self):
        """Ayarlar sekmesi"""
        settings_widget = QWidget()
        layout = QVBoxLayout(settings_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Kaynak Grup
        layout.addWidget(QLabel("🔗 Kaynak Grup Linki"))
        self.source_group = QLineEdit()
        self.source_group.setPlaceholderText("https://t.me/groupname veya @groupname")
        self.source_group.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(self.source_group)
        
        # Hedef Grup
        layout.addWidget(QLabel("🎯 Hedef Grup Linki"))
        self.target_group = QLineEdit()
        self.target_group.setPlaceholderText("https://t.me/targetgroup veya @targetgroup")
        self.target_group.setStyleSheet(self.get_input_stylesheet())
        layout.addWidget(self.target_group)
        
        # Delay
        layout.addWidget(QLabel("⏱️ Üyeler Arası Gecikme (Saniye)"))
        delay_layout = QHBoxLayout()
        self.delay_spin = QSpinBox()
        self.delay_spin.setValue(2)
        self.delay_spin.setMinimum(1)
        self.delay_spin.setMaximum(60)
        self.delay_spin.setStyleSheet(self.get_input_stylesheet())
        delay_layout.addWidget(self.delay_spin)
        delay_layout.addStretch()
        layout.addLayout(delay_layout)
        
        layout.addWidget(QLabel("💡 Tavsiye: 2-5 saniye arasında kullanın"))
        
        # Kaydet Butonu
        save_btn = QPushButton("💾 AYARLARI KAYDET")
        save_btn.setStyleSheet(self.get_button_stylesheet())
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        layout.addStretch()
        self.tabs.addTab(settings_widget, "⚙️ Ayarlar")
    
    def create_scraper_tab(self):
        """Çekme sekmesi"""
        scraper_widget = QWidget()
        layout = QVBoxLayout(scraper_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # İstatistik
        stats_layout = QHBoxLayout()
        self.total_label = QLabel("📊 Toplam: 0")
        self.success_label = QLabel("✅ Başarılı: 0")
        self.failed_label = QLabel("❌ Başarısız: 0")
        for label in [self.total_label, self.success_label, self.failed_label]:
            label.setStyleSheet("font-size: 13px; font-weight: bold; color: #00bfff;")
            stats_layout.addWidget(label)
        layout.addLayout(stats_layout)
        
        # Progress Bar
        self.progress = QProgressBar()
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                border: 2px solid {Config.COLOR_ACCENT};
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }}
            QProgressBar::chunk {{
                background-color: {Config.COLOR_ACCENT};
            }}
        """)
        layout.addWidget(self.progress)
        
        # Çekme Tablosu
        self.scraper_table = QTableWidget()
        self.scraper_table.setColumnCount(4)
        self.scraper_table.setHorizontalHeaderLabels(["User ID", "Kullanıcı Adı", "Durum", "Zaman"])
        self.scraper_table.setStyleSheet(self.get_table_stylesheet())
        layout.addWidget(self.scraper_table)
        
        # Butonlar
        button_layout = QHBoxLayout()
        
        start_btn = QPushButton("▶️ ÇEKMEYE BAŞLA")
        start_btn.setStyleSheet(self.get_button_stylesheet())
        start_btn.clicked.connect(self.start_scraping)
        button_layout.addWidget(start_btn)
        
        stop_btn = QPushButton("⏹️ DURDUR")
        stop_btn.setStyleSheet(self.get_button_stylesheet())
        stop_btn.clicked.connect(self.stop_scraping)
        button_layout.addWidget(stop_btn)
        
        layout.addLayout(button_layout)
        self.tabs.addTab(scraper_widget, "🚀 Çekme")
    
    def create_stats_tab(self):
        """İstatistikler sekmesi"""
        stats_widget = QWidget()
        layout = QVBoxLayout(stats_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setStyleSheet(self.get_input_stylesheet())
        self.stats_text.setText("📊 İstatistikler burada gösterilecek...")
        layout.addWidget(self.stats_text)
        
        self.tabs.addTab(stats_widget, "📊 İstatistikler")
    
    def create_logs_tab(self):
        """Loglar sekmesi"""
        logs_widget = QWidget()
        layout = QVBoxLayout(logs_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setStyleSheet(self.get_input_stylesheet())
        self.logs_text.setText("📝 Loglar burada gösterilecek...\n")
        layout.addWidget(self.logs_text)
        
        # Temizle butonu
        clear_btn = QPushButton("🗑️ LOGLARı TEMIZLE")
        clear_btn.setStyleSheet(self.get_button_stylesheet())
        clear_btn.clicked.connect(lambda: self.logs_text.setText("📝 Loglar temizlendi.\n"))
        layout.addWidget(clear_btn)
        
        self.tabs.addTab(logs_widget, "📝 Loglar")
    
    def authenticate(self):
        """Telegram'a bağlan"""
        phone = self.phone_input.text().strip()
        if not phone:
            QMessageBox.warning(self, "⚠️ Hata", "Lütfen telefon numarası girin!")
            return
        
        if not Config.API_ID or not Config.API_HASH:
            QMessageBox.critical(self, "❌ Hata", "API_ID ve API_HASH boş!\n\nBoyka.py dosyasının Config kısmında doldurun.")
            return
        
        self.auth_status.setText("⏳ Doğrulama Bekleniyor...")
        self.auth_status.setStyleSheet(f"color: {Config.COLOR_WARNING}; font-size: 14px; font-weight: bold;")
        self.log_message(f"📱 {phone} numarasıyla doğrulama başlatıldı...")
        
        QMessageBox.information(self, "✅ Doğrulama", f"SMS kodu {phone} numarasına gönderildi.\n\nLütfen SMS'inizi kontrol edin ve kodu girin.")
    
    def save_settings(self):
        """Ayarları kaydet"""
        source = self.source_group.text().strip()
        target = self.target_group.text().strip()
        delay = self.delay_spin.value()
        
        if not source or not target:
            QMessageBox.warning(self, "⚠️ Hata", "Lütfen grup linklerini girin!")
            return
        
        if delay < 2:
            QMessageBox.warning(self, "⚠️ Uyarı", "Çok düşük delay değeri hesabınızı bloklatabilir!\n\n2-5 saniye arası önerilir.")
            return
        
        self.log_message(f"✅ Ayarlar kaydedildi:")
        self.log_message(f"   📌 Kaynak: {source}")
        self.log_message(f"   📌 Hedef: {target}")
        self.log_message(f"   ⏱️  Delay: {delay} saniye")
        QMessageBox.information(self, "✅ Başarılı", "Ayarlar kaydedildi!")
    
    def start_scraping(self):
        """Çekmeye başla"""
        if not self.is_authenticated:
            QMessageBox.warning(self, "⚠️ Hata", "Lütfen önce doğrulama yapın!")
            return
        
        source = self.source_group.text().strip()
        target = self.target_group.text().strip()
        
        if not source or not target:
            QMessageBox.warning(self, "⚠️ Hata", "Lütfen grup linklerini girin!")
            return
        
        self.scraping_active = True
        self.log_message(f"🚀 Çekme işlemi başlatıldı!")
        self.log_message(f"   📌 Kaynak Grup: {source}")
        self.log_message(f"   📌 Hedef Grup: {target}")
        self.statusBar().showMessage("🚀 Çekme işlemi devam ediyor...")
    
    def stop_scraping(self):
        """Çekmeyi durdur"""
        if self.scraping_active:
            self.scraping_active = False
            self.log_message("⏹️ Çekme işlemi durduruldu.")
            self.statusBar().showMessage("⏹️ Durduruldu")
        else:
            QMessageBox.information(self, "ℹ️ Bilgi", "Şu anda çekme işlemi aktif değil.")
    
    def log_message(self, message: str):
        """Log mesajı ekle"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs_text.append(f"[{timestamp}] {message}")
        logger.info(message)
    
    # ==================== STİL ŞABLONLARI ====================
    
    def get_dark_stylesheet(self):
        """Koyu tema stil sayfası"""
        return f"""
            QMainWindow, QWidget {{
                background-color: {Config.COLOR_PRIMARY};
                color: white;
            }}
            QLabel {{
                color: white;
            }}
            QTabWidget::pane {{
                border: 2px solid {Config.COLOR_ACCENT};
            }}
            QMenuBar {{
                background-color: {Config.COLOR_SECONDARY};
                color: white;
            }}
            QMenuBar::item:selected {{
                background-color: {Config.COLOR_ACCENT};
                color: black;
            }}
        """
    
    def get_input_stylesheet(self):
        """Input alanları stil sayfası"""
        return f"""
            QLineEdit, QTextEdit, QSpinBox {{
                background-color: {Config.COLOR_SECONDARY};
                color: white;
                border: 2px solid {Config.COLOR_ACCENT};
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
            }}
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
                border: 2px solid {Config.COLOR_ACCENT};
                background-color: {Config.COLOR_PRIMARY};
            }}
        """
    
    def get_button_stylesheet(self):
        """Buton stil sayfası"""
        return f"""
            QPushButton {{
                background-color: {Config.COLOR_ACCENT};
                color: black;
                border: none;
                border-radius: 5px;
                padding: 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #00d9ff;
            }}
            QPushButton:pressed {{
                background-color: #0099cc;
            }}
        """
    
    def get_table_stylesheet(self):
        """Tablo stil sayfası"""
        return f"""
            QTableWidget {{
                background-color: {Config.COLOR_SECONDARY};
                alternate-background-color: {Config.COLOR_PRIMARY};
                gridline-color: {Config.COLOR_ACCENT};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {Config.COLOR_ACCENT};
                color: black;
                padding: 5px;
                border: none;
                font-weight: bold;
            }}
        """

# ==================== MAIN ====================

def main():
    """Ana program"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
