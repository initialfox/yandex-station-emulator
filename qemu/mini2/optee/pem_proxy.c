/* Local probe adapter for the supplied Quasar PEM pair. No key generation. */
typedef __SIZE_TYPE__ size_t;
typedef struct bio_st BIO;
typedef struct evp_pkey_st EVP_PKEY;
typedef struct evp_md_ctx_st EVP_MD_CTX;
extern int socket(int,int,int),bind(int,const void*,unsigned),listen(int,int),accept(int,void*,void*),close(int),unlink(const char*);
extern int read(int,void*,unsigned),write(int,const void*,unsigned),puts(const char*),printf(const char*,...);
extern void *memcpy(void*,const void*,unsigned),*memset(void*,int,unsigned);
extern unsigned strlen(const char*);
extern BIO *BIO_new_file(const char*,const char*);
extern int BIO_free(BIO*);
extern EVP_PKEY *PEM_read_bio_PrivateKey(BIO*,EVP_PKEY**,void*,void*);
extern EVP_PKEY *PEM_read_bio_PUBKEY(BIO*,EVP_PKEY**,void*,void*);
extern int EVP_PKEY_cmp(const EVP_PKEY*,const EVP_PKEY*);
extern void EVP_PKEY_free(EVP_PKEY*);
extern int i2d_PUBKEY(EVP_PKEY*,unsigned char**);
extern EVP_MD_CTX *EVP_MD_CTX_new(void);
extern void EVP_MD_CTX_free(EVP_MD_CTX*);
extern const void *EVP_sha256(void);
extern int EVP_DigestSignInit(EVP_MD_CTX*,void*,const void*,void*,EVP_PKEY*);
extern int EVP_DigestSign(EVP_MD_CTX*,unsigned char*,size_t*,const unsigned char*,size_t);
extern void *EVP_PKEY_get1_RSA(EVP_PKEY*);
extern int RSA_private_decrypt(int,const unsigned char*,unsigned char*,void*,int);
extern void RSA_free(void*);
extern int RSA_padding_check_PKCS1_type_2(unsigned char*,int,const unsigned char*,int,int);
extern int RSA_padding_check_PKCS1_OAEP_mgf1(unsigned char*,int,const unsigned char*,int,int,const unsigned char*,int,const void*,const void*);
extern const void *EVP_sha1(void);
extern int fflush(void*);
static unsigned char request[65536],nested[65536],response[65536],result[8192],public_der[4096];
static int exact(int fd,void *p,unsigned n,int out) { unsigned k=0; while(k<n){int r=out?write(fd,(char*)p+k,n-k):read(fd,(char*)p+k,n-k);if(r<=0)return 0;k+=r;}return 1; }
static unsigned varint(unsigned char *p,unsigned v){unsigned n=0;do{p[n]=(v&127)|(v>127?128:0);v>>=7;n++;}while(v);return n;}
static unsigned getvar(const unsigned char *p,unsigned n,unsigned *offset){unsigned v=0,s=0;while(*offset<n&&s<32){unsigned c=p[(*offset)++];v|=(c&127)<<s;if(!(c&128))return v;s+=7;}return 0;}
static unsigned bytes(unsigned char *p,unsigned field,const unsigned char *data,unsigned n){unsigned k=varint(p,field*8+2);k+=varint(p+k,n);memcpy(p+k,data,n);return k+n;}
int main(int argc,char **argv,char **env){
 (void)env;if(argc!=4){puts("usage: pem_proxy private.pem public.pem socket");return 2;}
 BIO *bio=BIO_new_file(argv[1],"r");if(!bio)return 3;
 EVP_PKEY *key=PEM_read_bio_PrivateKey(bio,0,0,0);BIO_free(bio);if(!key)return 4;
 bio=BIO_new_file(argv[2],"r");if(!bio)return 5;
 EVP_PKEY *public_key=PEM_read_bio_PUBKEY(bio,0,0,0);BIO_free(bio);
 if(!public_key||EVP_PKEY_cmp(key,public_key)!=1){EVP_PKEY_free(public_key);return 5;}
 /* KeymasterProxyClient wraps these SubjectPublicKeyInfo DER bytes in PEM. */
 int public_size=i2d_PUBKEY(public_key,0);
 if(public_size<=0||public_size>(int)sizeof(public_der)){EVP_PKEY_free(public_key);return 5;}
 unsigned char *der_end=public_der;
 int encoded_size=i2d_PUBKEY(public_key,&der_end);EVP_PKEY_free(public_key);
 if(encoded_size!=public_size)return 5;
 struct {unsigned short family;char path[108];} addr;memset(&addr,0,sizeof(addr));addr.family=1;
 if(strlen(argv[3])>=108)return 6;memcpy(addr.path,argv[3],strlen(argv[3]));unlink(argv[3]);
 int server=socket(1,1,0);if(server<0||bind(server,&addr,sizeof(addr))||listen(server,8))return 7;
 puts("PEM adapter listening (local experiment)");
 fflush(0);
 for(;;){int fd=accept(server,0,0);if(fd<0)continue;
  for(;;){unsigned char header[8];if(!exact(fd,header,8,0))break;
   if(header[0]!=0x42||header[1]!=0xfa||header[2]!=0x85||header[3]!=0x1f)break;
   unsigned n=(header[4]<<24)|(header[5]<<16)|(header[6]<<8)|header[7];if(n>sizeof(request)||!exact(fd,request,n,0))break;
   unsigned off=0,tag=getvar(request,n,&off),len=getvar(request,n,&off),field=tag>>3;
   if((tag&7)!=2||len>n-off)break;
   unsigned out_size=0,result_size=0;int ok=0;
   if(field==3){memcpy(result,public_der,public_size);result_size=public_size;ok=1;}
   if(field==1||field==2){unsigned j=off,inner=getvar(request,off+len,&j),size=getvar(request,off+len,&j);
    if(inner==10&&size<=off+len-j){
     if(field==1){size_t sig_size=sizeof(result);EVP_MD_CTX *ctx=EVP_MD_CTX_new();
      ok=ctx&&EVP_DigestSignInit(ctx,0,EVP_sha256(),0,key)==1&&EVP_DigestSign(ctx,result,&sig_size,request+j,size)==1;
      result_size=sig_size;EVP_MD_CTX_free(ctx);
     }else{
      void *rsa=EVP_PKEY_get1_RSA(key);
      int got=-1;
      if(rsa){
       /* Explicit checks also avoid OpenSSL 3's implicit PKCS1 rejection
        * returning synthetic plaintext before the OAEP fallback is tried. */
       unsigned char raw[8192];
       int raw_size=size<=sizeof(raw)?RSA_private_decrypt(size,request+j,raw,rsa,3):-1;
       if(raw_size>0){
        got=RSA_padding_check_PKCS1_type_2(result,sizeof(result),raw,raw_size,raw_size);
        if(got<0){
         got=RSA_padding_check_PKCS1_OAEP_mgf1(result,sizeof(result),raw,raw_size,raw_size,0,0,EVP_sha1(),EVP_sha1());
         if(got>=0)puts("decrypt padding=OAEP-SHA1");
         else {
          got=RSA_padding_check_PKCS1_OAEP_mgf1(result,sizeof(result),raw,raw_size,raw_size,0,0,EVP_sha256(),EVP_sha256());
          if(got>=0)puts("decrypt padding=OAEP-SHA256");
         }
        }
       }
       memset(raw,0,sizeof(raw));
      }
      printf("decrypt input_bytes=%u valid_padding=%d\n",size,got>=0);
      RSA_free(rsa);if(got>=0){ok=1;result_size=got;}
     }
    }
   }
   if(ok){unsigned k=bytes(nested,1,result,result_size);out_size=bytes(response,field+1,nested,k);}
   else {unsigned char err[]={8,1};out_size=bytes(response,1,err,sizeof(err));}
   printf("operation=%u success=%d bytes=%u\n",field,ok,result_size);
   fflush(0);
   header[4]=out_size>>24;header[5]=out_size>>16;header[6]=out_size>>8;header[7]=out_size;
   if(!exact(fd,header,8,1)||!exact(fd,response,out_size,1))break;
  }close(fd);
 }
}
#if defined(__arm__)
extern int __libc_start_main(int(*)(int,char**,char**),int,char**,void*,void*,void*,void*);
void start_c(unsigned *stack){__libc_start_main(main,stack[0],(char**)(stack+1),0,0,0,stack);}
__asm__(".text\n.arm\n.global _start\n_start:\nmov r0, sp\nbl start_c\nmov r7, #1\nsvc #0\n");
#endif
