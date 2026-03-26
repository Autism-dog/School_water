[app]
title           = School Water
package.name    = schoolwater
package.domain  = org.schoolwater
source.dir      = .
source.include_exts = py,png,jpg,kv,atlas,wasm
version         = 1.0.0

requirements = python3,kivy==2.3.0,pytz,pyjnius

# Android permissions
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION

android.api         = 34
android.minapi      = 26
android.ndk         = 25b
android.archs       = arm64-v8a, armeabi-v7a
orientation         = portrait

# Gradle
android.gradle_dependencies = com.android.support:support-v4:28.0.0

# Presplash + icon
# presplash.filename = %(source.dir)s/data/presplash.png
# icon.filename      = %(source.dir)s/data/icon.png

[buildozer]
log_level = 2
warn_on_root = 1
