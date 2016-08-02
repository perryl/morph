/* Copyright (C) 2014-2016  Codethink Limited

  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; version 2 of the License.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License along
  with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include <fcntl.h>
#include <sys/types.h>
#include <sys/stat.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>

#include <stdint.h>
#include <ftw.h>
#include <errno.h>
#include <err.h>

char *readlinka(char const *path){
    size_t buflen = BUFSIZ;
    char *buf = malloc(buflen);
    ssize_t read;
    while ((read = readlink(path, buf, buflen - 1)) >= buflen - 1) {
        char *newbuf = realloc(buf, buflen * 2);
        if (newbuf == NULL) {
            goto failure;
        }
        buf = newbuf;
        buflen = buflen * 2;
    }
    buf[read] = '\0';
    return buf;
failure:
    free(buf);
    return NULL;
}

int copy_file_paths(char const *source_file, char const *target_file) {
    int source_fd;
    int target_fd;
    int ret = -1;
    struct stat st;
    if ((source_fd = open(source_file, O_RDONLY)) == -1) {
        return ret;
    }
    if (fstat(source_fd, &st) == -1) {
        perror("stat");
        ret = -2;
        goto cleanup_in;
    }
    if ((target_fd = open(target_file, O_WRONLY|O_CREAT, st.st_mode)) == -1) {
        ret = -3;
        goto cleanup_in;
    }
    ssize_t read;
    while ((read = sendfile(target_fd, source_fd, NULL, BUFSIZ)) > 0);
    if (read < 0) {
       perror("sendfile");
       ret = -4;
    }
    ret = 0;
cleanup_all:
    close(target_fd);
cleanup_in:
    close(source_fd);
    return ret;
}

int copy_entry(const char *fpath, const struct stat *sb, int typeflag,
               struct FTW *ftwbuf) {
    int ret = 0;
    char *target_path = NULL;
    if (strncmp(fpath, "./.git", 6) == 0) {
        /* Skip ./.git directory and its contents. */
        return 0;
    }
    if (asprintf(&target_path, "%s/%s", getenv("DESTDIR"), fpath) == -1) {
        return -1;
    }
    switch (typeflag) {
        case FTW_F:
            /* Copy file */
            if ((ret = copy_file_paths(fpath, target_path)) < 0) {
                perror("Copy file");
                ret = -1;
            }
            break;
        case FTW_D:
        case FTW_DNR: {
            /* Copy directory */
            if (mkdir(target_path, sb->st_mode)) {
                if (errno != EEXIST) {
                    perror("mkdir");
                    ret = -1;
                }
            }
            break;
        }
        case FTW_NS:
        case FTW_SL:
        case FTW_SLN: {
            /* Create symlink */
            char *link_target = readlinka(fpath);
            if (link_target == NULL) {
                perror("readlink");
                ret = -1;
            }
            if (symlink(link_target, target_path) == -1) {
                perror("symlink");
                ret = -1;
            }
            break;
        }
    }
cleanup:
    free(target_path);
    return ret;
}

int copy_file_objects(FILE *source, FILE *target) {
    char buffer[BUFSIZ];
    size_t read;
    do {
        read = fread(buffer, 1, sizeof(buffer), source);
        fwrite(buffer, 1, read, target);
    } while (!feof(source) && !feof(target));
    return (ferror(source) || ferror(target)) ? -1 : 0;
}

int run_commands(FILE *cmdstream){
    int ret = 1;
    ssize_t read;
    size_t len = 0;
    char *line = NULL;

    ret = 0;
    while ((read = getline(&line, &len, cmdstream)) != -1) {
        if (line[read - 1] == '\n') line[read - 1] = '\0';
        if (strcmp(line, "copy files") == 0) {
            /* Recursively copy contents of current dir to DESTDIR */
            if (nftw(".", copy_entry, 20, FTW_PHYS)) {
                ret = 1;
                break;
            }
        } else if (strcmp(line, "false") == 0 ||
                   strstr(line, "false ") == line) {
            ret = 1;
            break;
        } else if (strstr(line, "echo ") == line) {
            if (puts(line + sizeof("echo ") - 1) == EOF){
                perror("echo");
                ret = 1;
                break;
            }
        } else if (strstr(line, "printvar ") == line) {
            char const *var = line + sizeof("printvar ") - 1;
            fprintf(stdout, "%s\n", getenv(var));
        } else if (strstr(line, "create file ") == line) {
            char const *filename = line + sizeof("create file ") -1;
            FILE *outfile = fopen(filename, "w");
            if (outfile == NULL){
                ret = 1;
                err(errno, "Opening %s for write failed", filename);
                break;
            }
            if (copy_file_objects(cmdstream, outfile) < 0) {
                ret = 1;
                err(errno, "Writing to %s failed", filename);
                fclose(outfile);
                break;
            }
            fclose(outfile);
        } else if (strstr(line, "file exists ") == line) {
            char const *filename = line + sizeof("file exists ") -1;
            fprintf(stderr, "FILENAME: %s\n", filename);
            struct stat st;
            int result = stat(filename, &st);
            return result != 0;
        } else if (line[0] == '#' || strstr(line, "set ") == line) {
            /* Comments and set commands are ignored */
            continue;
        } else {
            fprintf(stderr, "Unrecognized command: %s\n", line);
            ret = 127;
            break;
        }
    }
    free(line);
    return ret;
}

int main(int argc, char *argv[]) {
    if (argc == 5 && strcmp(argv[1], "-x") == 0 \
            && strcmp(argv[2], "-e") == 0 \
            && strcmp(argv[3], "-c") == 0) {
        size_t cmdlen = strlen(argv[4]);
        FILE *cmdstream = fmemopen(argv[4], cmdlen, "r");
        return run_commands(cmdstream);
    } else if (argc == 2) {
        FILE *cmdstream = fopen(argv[1], "r");
        return run_commands(cmdstream);
    } else {
        fprintf(stderr, "Usage: %s -x -e -c COMMAND|%s SCRIPT\n",
                argv[0], argv[0]);
        return 1;
    }
}
