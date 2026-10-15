ARCHS = armv7
TARGET = iphone:clang:9.2:9.0
include $(THEOS)/makefiles/common.mk
TOOL_NAME = shockstream-waked
shockstream-waked_FILES = main.m
shockstream-waked_FRAMEWORKS = Foundation CoreFoundation Security
shockstream-waked_CFLAGS = -fobjc-arc -Wall -Wextra
shockstream-waked_CODESIGN_FLAGS = -Sentitlements.plist
shockstream-waked_INSTALL_PATH = /usr/libexec
include $(THEOS_MAKE_PATH)/tool.mk
