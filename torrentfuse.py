#!/usr/bin/env python
# -*- coding:utf-8 -*-

# Install libtorrent and fusepy (pip)
# Usage: script.py torrentfile.torrent mountpoint
# Actual files will be downloaded to working directory
from __future__ import with_statement

import os
import sys
import errno
import math
from fuse import FUSE, FuseOSError, Operations

import libtorrent as lt
import time
import stat
import signal
run = True
def sighandler(s):
    run = False
    sys.exit(0)
signal.signal(signal.SIGTERM,sighandler)
signal.signal(signal.SIGINT,sighandler)

h = 0
class TorrentFS(Operations):
    def __init__(self, torrentfile):
        self.session = lt.session()
        self.torrentfile = torrentfile
        self.session.listen_on(6881,6891)
        e = lt.bdecode(open(torrentfile,"rb").read())
        self.tinfo = lt.torrent_info(e)
        self.filetree = (None,self.populatetree(0))
        params = { "save_path" : '.', "storage_mode" : lt.storage_mode_t.storage_mode_sparse, "ti" : self.tinfo }
        self.th = self.session.add_torrent(params)
        self.th.prioritize_pieces([0]*self.tinfo.num_pieces())
        self.th.set_upload_limit(10*1024)
        print(self.filetree)
    def populatetree(self,cur):
        ret = {}
        for x in self.getfilelist():
            print(x)
            p1 = x.split("/")
            p1 = p1[cur:]
            if len(p1) > 1:
                if not p1[0] in ret:
                    ret[p1[0]] = (self.getfileinfo(x),self.populatetree(cur+1))
                else:
                    n = ret[p1[0]][1]
                    n.update(self.populatetree(cur+1))
                    ret[p1[0]] = (None,n)
            else:
                if not p1[0] in ret:
                    ret[p1[0]] = (self.getfileinfo(x),{})
                else:
                    n = ret[p1[0]][1]
                    ret[p1[0]] = (None,n)
        return ret
    def getpath(self,path):
        path = path.strip("/")
        cur = self.filetree
        if path == "":
            return cur
        for x in path.split("/"):
            if not x in cur[1]:
                raise FuseOSError(errno.ENOENT)
            cur = cur[1][x]
        return cur
    def getfilelist(self):
        for x in self.tinfo.files():
            yield x.path
    def getfileinfo(self,pathstripped):
        print("finfo",pathstripped)
        for x in self.tinfo.files():
            if pathstripped == x.path:
                return x
        return None
    # Filesystem methods
    # ==================

    #def access(self, path, mode):
        #print("access",path,mode)
        #path = path.strip("/")
        #if not path in self.getfilelist():
            #raise FuseOSError(errno.ENOENT)
    def chmod(self, path, mode):
        raise FuseOSError(errno.EROFS)

    def chown(self, path, uid, gid):
        raise FuseOSError(errno.EROFS)

    def getattr(self, path, fh=None):
        #print("getattr",path)
        info = self.getpath(path)[0]
        
        st = os.lstat(self.torrentfile)
        
       
        if info:
            d = dict(st_mode=(stat.S_IFREG | 0o666), st_nlink=2,st_atime=time.time(),st_ctime=st.st_ctime,st_size=info.size)
        else:
            d = dict(st_mode=(stat.S_IFDIR | 0o755), st_nlink=2)
        
        return d

    def readdir(self, path, fh):
        c = 0
        #print("list",path)
        dirents = ['.', '..']
        p = self.getpath(path)
        for x in p[1]:
            dirents.append(x)
        return dirents

    def readlink(self, path):
        #print("readlink",path)
        raise FuseOSError(errno.ENOENT)

    def mknod(self, path, mode, dev):
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path):
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path, mode):
        raise FuseOSError(errno.EROFS)

    def statfs(self, path):
        return { "f_bavail" : 0 ,
                "f_bfree" : 0,
                "f_blocks" : self.tinfo.num_pieces(),
                "f_bsize": self.tinfo.piece_length(),
                "f_favail": 0,
                "f_ffree": 0,
                "f_files": len(self.tinfo.files()),
                "f_flag": 0,
                "f_frsize": self.tinfo.piece_length(),
                "f_namemax": 1024 }

    def unlink(self, path):
        raise FuseOSError(errno.EROFS)

    def symlink(self, name, target):
        raise FuseOSError(errno.EROFS)

    def rename(self, old, new):
        raise FuseOSError(errno.EROFS)

    def link(self, target, name):
        raise FuseOSError(errno.EROFS)

    def utimens(self, path, times=None):
        raise FuseOSError(errno.EROFS)

    # File methods
    # ============

    def open(self, path, flags):
        global h
        if flags & os.O_WRONLY or flags & os.O_RDWR:
            raise FuseOSError(errno.EROFS)
        h = h + 1
        return h

    def create(self, path, mode, fi=None):
        raise FuseOSError(errno.EROFS)

    def read(self, path, length, offset, fh):
        #TODO: Offset file multipli
        info = self.getpath(path)[0]
        offset += info.offset
        psize = self.tinfo.piece_length()
        
        neededpieces = list(range(int(math.floor(offset/psize)),int(math.ceil((offset+length)/psize+1))))
        comp = True
        for x in neededpieces:
            comp = comp and self.th.have_piece(x)
        
        if comp:
            f = open(path.strip("/"),"rb")
            f.seek(offset-info.offset)
            data = f.read(length)
            f.close()
            return data
        else:
            print("Asking pieces",neededpieces)
            curprio = list(self.th.piece_priorities())
            for x in neededpieces:
                if x < len(curprio):
                    curprio[x] = 1
            self.th.prioritize_pieces(curprio)
            comp = False
            while not comp:
                comp = True
                for x in neededpieces:
                    if x < len(curprio):
                        comp = comp and self.th.have_piece(x)
                s = self.th.status()
                
                state_str = ['queued', 'checking', 'downloading metadata', \
                        'downloading', 'finished', 'seeding', 'allocating']
                sys.stdout.write("\r%.2f%% complete (down: %.1f kb/s up: %.1f kB/s peers: %d) %s            " % \
                        (s.progress * 100, s.download_rate / 1000, s.upload_rate / 1000, \
                        s.num_peers, state_str[s.state]))
                sys.stdout.flush()
                time.sleep(1.0)
            self.th.flush_cache()
            f = open(path.strip("/"),"rb")
            print("Read",offset,info.offset,offset-info.offset)
            f.seek(offset-info.offset)
            data = f.read(length)
            f.close()
            return data

    def write(self, path, buf, offset, fh):
        FuseOSError(errno.EROFS)

    def truncate(self, path, length, fh=None):
        FuseOSError(errno.EROFS)

    def flush(self, path, fh):
        FuseOSError(errno.EROFS)

    def release(self, path, fh):
        global h
        h = h - 1 

    def fsync(self, path, fdatasync, fh):
        FuseOSError(errno.EROFS)


def main(mountpoint, torrentfile):
    FUSE(TorrentFS(torrentfile), mountpoint, foreground=True)

if __name__ == '__main__':
    if len(sys.argv) == 3:
    
        main(sys.argv[2], sys.argv[1])
    else:
        print("torrentfuse.py torrent mountpoint ")
