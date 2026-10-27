/* Present host radio scan results to firmware using a wired LAN transport.
 * Wi-Fi PSKs are intentionally neither used nor stored: this is NOT a radio
 * authenticator. The real wpa_supplicant wired backend owns link state.
 */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define MAX 65536
static int server, backend;
static struct sockaddr_un subscribers[32];
static int active[32];
static void sendto_client(const char *s, size_t n, struct sockaddr_un *to) {
    sendto(server,s,n,0,(void*)to,sizeof(*to));
}
static void event(const char *s,size_t n) {
    for(int i=0;i<32;i++) if(active[i]) sendto_client(s,n,&subscribers[i]);
}
static int bind_socket(const char *path) {
    int fd=socket(AF_UNIX,SOCK_DGRAM,0);
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    if(strlen(path)>=sizeof(addr.sun_path)) exit(2);
    strcpy(addr.sun_path,path);unlink(path);
    if(fd<0||bind(fd,(void*)&addr,sizeof(addr))) {perror("bind");exit(2);}
    chmod(path,0600);return fd;
}
static int exchange(const char *cmd,char *out) {
    if(send(backend,cmd,strlen(cmd),0)<0)return -1;
    for(;;) {
        fd_set f;FD_ZERO(&f);FD_SET(backend,&f);
        struct timeval t={.tv_sec=4};
        if(select(backend+1,&f,NULL,NULL,&t)<=0)return -1;
        int n=recv(backend,out,MAX-1,0);if(n<0)return -1;out[n]=0;
        if(out[0]=='<') {event(out,n);continue;}
        return n;
    }
}
int main(int argc,char **argv) {
    if(argc!=4) {fprintf(stderr,"usage: wpa-lan-proxy FRONT BACK SCANFILE\n");return 2;}
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    snprintf(addr.sun_path,sizeof(addr.sun_path),"%s",argv[2]);
    char local[100];snprintf(local,sizeof(local),"/tmp/wpa-lan-%d",getpid());
    backend=bind_socket(local);
    if(connect(backend,(void*)&addr,sizeof(addr))) {perror("backend");return 2;}
    server=bind_socket(argv[1]);
    char *cmd=malloc(MAX),*out=malloc(MAX);
    if(!cmd||!out)return 2;
    if(exchange("ATTACH",out)<0)return 2;
    for(;;) {
        fd_set f;FD_ZERO(&f);FD_SET(server,&f);FD_SET(backend,&f);
        if(select((server>backend?server:backend)+1,&f,NULL,NULL,NULL)<0) {
            if(errno==EINTR)continue;
            return 2;
        }
        if(FD_ISSET(backend,&f)) {
            int n=recv(backend,out,MAX-1,0);
            if(n>0&&out[0]=='<')event(out,n);
        }
        if(!FD_ISSET(server,&f))continue;
        struct sockaddr_un client={0};socklen_t size=sizeof(client);
        int n=recvfrom(server,cmd,MAX-1,0,(void*)&client,&size);
        if(n<=0)continue;
        cmd[n]=0;
        /* Log command names only. Never arguments, SSIDs or credentials. */
        size_t token=strcspn(cmd," \n");
        fprintf(stderr,"wpa command %.*s\n",(int)token,cmd);
        if(!strcmp(cmd,"ATTACH")||!strcmp(cmd,"DETACH")) {
            int found=-1,empty=-1;
            for(int i=0;i<32;i++) {
                if(active[i]&&!strcmp(subscribers[i].sun_path,client.sun_path))found=i;
                if(!active[i])empty=i;
            }
            if(cmd[0]=='A'&&found<0&&empty>=0) {
                subscribers[empty]=client;active[empty]=1;
            } else if(cmd[0]=='D'&&found>=0)active[found]=0;
            sendto_client("OK\n",3,&client);continue;
        }
        if(!strcmp(cmd,"SCAN_RESULTS")) {
            FILE *fp=fopen(argv[3],"r");
            n=fp?(int)fread(out,1,MAX-1,fp):0;if(fp)fclose(fp);
            if(!n) {strcpy(out,"bssid / frequency / signal level / flags / ssid\n");n=strlen(out);}
        } else if(!strncmp(cmd,"SCAN",4)&&(cmd[4]==0||cmd[4]==' ')) {
            strcpy(out,"OK\n");n=3;
        } else if(!strncmp(cmd,"SET_NETWORK ",12)) {
            char field[64];int id;
            if(sscanf(cmd+12,"%d %63s",&id,field)!=2) {strcpy(out,"FAIL\n");n=5;}
            else if(!strcmp(field,"psk")||!strcmp(field,"sae_password")) {
                strcpy(out,"OK\n");n=3; /* Discard, never save. */
            } else if(!strcmp(field,"key_mgmt")) {
                char replacement[100];snprintf(replacement,sizeof(replacement),"SET_NETWORK %d key_mgmt NONE",id);
                n=exchange(replacement,out);
            } else n=exchange(cmd,out);
        } else n=exchange(cmd,out);
        if(n<0) {strcpy(out,"FAIL\n");n=5;}
        sendto_client(out,n,&client);
        if(!strncmp(cmd,"SCAN",4)&&strncmp(cmd,"SCAN_RESULTS",12)) {
            const char *e="<3>CTRL-EVENT-SCAN-RESULTS\n";event(e,strlen(e));
        }
        explicit_bzero(cmd,MAX);
    }
}
