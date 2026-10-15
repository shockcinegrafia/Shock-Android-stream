// Root-enumerated monitor setup. Runs elevated only after the app's install button.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <setupapi.h>
#include <newdev.h>
#include <filesystem>
#include <string>
#include <cwchar>
#pragma comment(lib,"setupapi.lib")
#pragma comment(lib,"newdev.lib")

static const wchar_t HardwareId[]=L"Root\\MttVDD\0";
static bool matches(HDEVINFO list,SP_DEVINFO_DATA *device) {
    wchar_t ids[4096]={};DWORD type=0;
    if(!SetupDiGetDeviceRegistryPropertyW(list,device,SPDRP_HARDWAREID,&type,(BYTE*)ids,sizeof(ids),nullptr))return false;
    for(const wchar_t *id=ids;*id;id+=wcslen(id)+1)if(_wcsicmp(id,HardwareId)==0)return true;
    return false;
}
int wmain(int argc,wchar_t **argv) {
    if(argc==2&&std::wstring(argv[1])==L"--self-test")return 0;
    if(argc!=3)return ERROR_INVALID_PARAMETER;
    std::wstring action=argv[1];std::filesystem::path inf=std::filesystem::absolute(argv[2]);
    if(action!=L"--install"&&action!=L"--uninstall")return ERROR_INVALID_PARAMETER;
    GUID guid={};wchar_t className[256]={};DWORD required=0;
    if(!SetupDiGetINFClassW(inf.c_str(),&guid,className,256,&required))return (int)GetLastError();
    HDEVINFO list=SetupDiGetClassDevsW(&guid,nullptr,nullptr,DIGCF_PRESENT);
    if(list==INVALID_HANDLE_VALUE)return (int)GetLastError();
    SP_DEVINFO_DATA existing={};existing.cbSize=sizeof(existing);bool found=false;
    for(DWORD i=0;SetupDiEnumDeviceInfo(list,i,&existing);i++)if(matches(list,&existing)){found=true;break;}
    if(action==L"--uninstall") {
        BOOL removed=!found||SetupDiCallClassInstaller(DIF_REMOVE,list,&existing);
        DWORD error=removed?ERROR_SUCCESS:GetLastError();SetupDiDestroyDeviceInfoList(list);return (int)error;
    }
    SetupDiDestroyDeviceInfoList(list);
    try {
        const std::filesystem::path config=L"C:\\VirtualDisplayDriver";
        std::filesystem::create_directories(config);
        if(!std::filesystem::exists(config/L"vdd_settings.xml"))
            std::filesystem::copy_file(inf.parent_path()/L"vdd_settings.xml",config/L"vdd_settings.xml");
    }catch(...){return ERROR_WRITE_FAULT;}
    HDEVINFO created=INVALID_HANDLE_VALUE;SP_DEVINFO_DATA device={};device.cbSize=sizeof(device);
    if(!found) {
        created=SetupDiCreateDeviceInfoList(&guid,nullptr);
        if(created==INVALID_HANDLE_VALUE)return (int)GetLastError();
        if(!SetupDiCreateDeviceInfoW(created,className,&guid,L"Shock Stream virtual monitor",nullptr,DICD_GENERATE_ID,&device)||
           !SetupDiSetDeviceRegistryPropertyW(created,&device,SPDRP_HARDWAREID,(const BYTE*)HardwareId,sizeof(HardwareId))||
           !SetupDiCallClassInstaller(DIF_REGISTERDEVICE,created,&device)) {
            DWORD error=GetLastError();SetupDiDestroyDeviceInfoList(created);return (int)error;
        }
    }
    BOOL reboot=FALSE;
    BOOL installed=UpdateDriverForPlugAndPlayDevicesW(nullptr,HardwareId,inf.c_str(),INSTALLFLAG_FORCE,&reboot);
    DWORD error=installed?(reboot?ERROR_SUCCESS_REBOOT_REQUIRED:ERROR_SUCCESS):GetLastError();
    if(created!=INVALID_HANDLE_VALUE) {
        if(!installed)SetupDiCallClassInstaller(DIF_REMOVE,created,&device);
        SetupDiDestroyDeviceInfoList(created);
    }
    return (int)error;
}
