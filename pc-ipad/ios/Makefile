ARCHS = armv7
TARGET = iphone:clang:9.2:9.0
include $(THEOS)/makefiles/common.mk
APPLICATION_NAME = ShockStream
ShockStream_FILES = main.m StreamController.m StreamConnection.m RemoteTLS.m HostDiscovery.m WakeBridge.m H264Decoder.m AudioPlayer.m GamepadView.m TouchView.m
ShockStream_FRAMEWORKS = UIKit Foundation AVFoundation AudioToolbox VideoToolbox CoreMedia CoreVideo QuartzCore Security
ShockStream_CFLAGS = -fobjc-arc -Wall -Wextra
ShockStream_RESOURCE_DIRS = Resources
include $(THEOS_MAKE_PATH)/application.mk
