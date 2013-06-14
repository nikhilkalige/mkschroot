import os
import tempfile


PERSONALITY = 'linux64' # Assume 64 bit for now
ARCH = { # Allow us to find the architecture from the personality name
    'linux64': 'amd64',
    'linux32': 'i386',
}


def execute(program, *args):
    """
        Execute a program and return True if it worked.
    """
    command = '%s %s' % (program, ' '.join([str(a) for a in args]))
    print "Starting", command
    assert os.system(command) == 0


def sudo(program, *args):
    """
        Execute a program with sudo rights
    """
    return execute("sudo", program, *args)


def schroot_sudo(name, program, *args):
    """
        Execute the program as root in the schroot environment.
    """
    return execute('schroot', '--chroot', name, '--user', 'root',
            '--directory', '/home/', '--',
        program, *args)


def build_config(config, name):
    """
        Build a chroot configuration by mixing the global and local configuration.
    """
    chroot = dict(conf={}, sources={})
    def copy_into(struct):
        for key, value in struct.items():
            if key in ["conf", "sources"]:
                for conf, choice in value.items():
                    chroot[key][conf] = choice
            else:
                chroot[key] = value
    copy_into(config['defaults'])
    copy_into(config['schroot'][name])
    def ensure(conf, value):
        if not chroot['conf'].has_key(conf):
            chroot['conf'][conf] = value
    ensure('directory', os.path.join(config['root'], name))
    ensure('personality', PERSONALITY)
    ensure('type', 'directory')
    ensure('description', '%s %s' % (
        chroot['release'], chroot['conf']['personality']))
    chroot['packages'] = chroot.get('packages', []) + \
        config.get('base-packages', [])
    for source, source_conf in chroot['sources'].items():
        if not source_conf.has_key('source'):
            source_conf['source'] = config['source']
    if chroot.has_key("variant"):
        for setup in ['config', 'copyfiles', 'fstab', 'nssdatabases']:
            if os.path.exists('/etc/schroot/%s/%s' % (chroot['variant'], setup)):
                ensure("setup.%s" % setup, "%s/%s" % (chroot['variant'], setup))
    return chroot


def create_root_file(location, content):
    """
        Create the file at location with the requested content.
        The file will be owned by root, but be world readable.
    """
    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.write(content)
    tmp_file.close()
    sudo("mv", tmp_file.name, location)
    sudo("chown", "root:root", location)
    sudo("chmod", "a+r", location)


def build_from_config(config):
    for name in config["schroot"].keys():
        chroot = build_config(config, name)
        conf_file = '[%s]\n' % name
        for conf, value in chroot['conf'].items():
            if conf == 'personality' and value == PERSONALITY:
                value = None
            elif issubclass(type(value), list):
                value = ','.join(value)
            if value:
                conf_file += "%s=%s\n" % (conf, value)
        file_loc = os.path.join('/etc/schroot/chroot.d/', name)
        if not os.path.exists(file_loc) or file(file_loc, "r").read() != conf_file:
            create_root_file(file_loc, conf_file)
        if not os.path.exists(chroot['conf']['directory']):
            bootstrap = ["debootstrap"]
            if chroot.has_key('variant'):
                bootstrap.append("--variant=%s" % chroot["variant"])
            bootstrap.append("--arch=%s" % ARCH[chroot['conf']['personality']])
            bootstrap.append(chroot['release'])
            bootstrap.append(chroot['conf']['directory'])
            bootstrap.append(config['source'])
            if config.has_key('http-proxy'):
                bootstrap.insert(0, 'http_proxy="%s"' % config['http-proxy'])
            sudo(*bootstrap)
            is_new = True
        else:
            is_new = False
        source_apt_conf = '/etc/apt/apt.conf'
        schroot_apt_conf = os.path.join(
                chroot['conf']['directory'], 'etc/apt/apt.conf')
        do_update = False
        if os.path.exists(source_apt_conf) and (
                not os.path.exists(schroot_apt_conf) or
                file(source_apt_conf).read() != file(schroot_apt_conf).read()):
            sudo('cp', source_apt_conf, schroot_apt_conf)
            do_update = True
        for source, location in chroot['sources'].items():
            source_path = os.path.join(chroot['conf']['directory'],
                'etc/apt/sources.list.d/', source +'.list')
            if not os.path.exists(source_path):
                create_root_file(source_path,
                    "deb %s %s %s\n" % (location['source'],
                        chroot['release'], source))
                do_update = True
        if do_update or not is_new:
            schroot_sudo(name, 'apt-get', 'update')
        if not is_new:
            schroot_sudo(name, 'apt-get', 'dist-upgrade', 'y', '--auto-remove')
        schroot_sudo(name, 'apt-get', 'install', '-y', '--auto-remove',
            *chroot['packages'])
