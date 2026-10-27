/* Private control-NIC-only D-Bus transport; independent of legacy adbd. */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static void bridge(int tcp) {
    int bus=socket(AF_UNIX,SOCK_STREAM,0);
    struct sockaddr_un a={.sun_family=AF_UNIX};
    strcpy(a.sun_path,"/run/dbus/system_bus_socket");
    if(bus<0||connect(bus,(void*)&a,sizeof(a)))_exit(2);
    char data[16384];
    for(;;) {
        fd_set f;FD_ZERO(&f);FD_SET(tcp,&f);FD_SET(bus,&f);
        if(select((tcp>bus?tcp:bus)+1,&f,NULL,NULL,NULL)<0) {
            if(errno==EINTR)continue;
            break;
        }
        int srcs[2]={tcp,bus};
        for(int i=0;i<2;i++)if(FD_ISSET(srcs[i],&f)) {
            ssize_t n=read(srcs[i],data,sizeof(data));
            if(n<=0)_exit(0);
            ssize_t offset=0;
            while(offset<n) {
                ssize_t written=send(srcs[1-i],data+offset,n-offset,MSG_NOSIGNAL);
                if(written<=0)_exit(0);
                offset+=written;
            }
        }
    }
    _exit(0);
}
int main(void) {
    signal(SIGCHLD,SIG_IGN);signal(SIGPIPE,SIG_IGN);
    int s=socket(AF_INET,SOCK_STREAM,0),yes=1;
    setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
    struct sockaddr_in a={.sin_family=AF_INET,.sin_port=htons(15558)};
    inet_pton(AF_INET,"10.0.2.15",&a.sin_addr);
    if(bind(s,(void*)&a,sizeof(a))||listen(s,8)) {perror("control bind");return 2;}
    for(;;) {
        int c=accept(s,NULL,NULL);
        if(c<0)continue;
        pid_t p=fork();
        if(p==0) {close(s);bridge(c);}
        close(c);
    }
}
