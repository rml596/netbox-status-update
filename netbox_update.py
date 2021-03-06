# Robert Lynch
# Based off of https://github.com/jamesb2147/netbox-status-loader/
#
#               ****NOTE: my deployment has a custom field for IPs called `Ignore from Automatic Status Update?`, if this is True, the script ignores the IP and continues.



# IDEA:
# Unregistered IPs, then if they don't ping and the description is 'Unregistered IP', delete them



import json, requests, dns.resolver, sys, argparse, syslog
from os import getuid
from ping3 import ping

from multiprocessing import Pool

# Trys to open env.json file
try:
    with open('env.json') as env:
        envars=json.load(env)
    api_base_url=envars['api_base_url']
    verifySSL=bool(envars['verifySSL'])
    apiToken=envars['apiToken']
    dnsList=envars['dnsList']
    deactiveIPid=envars['deactiveIPid']
    activeIPid=envars['activeIPid']
except:
    # hard code env-vars here, either edit in the ENV.json file or below
    #
    #
    api_base_url="http://localhost/api/ipam"
    verifySSL=False
    apiToken='abcdefghigklmnopqrstuvwxyz123456790'
    dnsList=['192.168.1.1', '192.168.2.1']
    deactiveIPid=3
    activeIPid=1

# Replaces token with the valid header --> {'Authorization':'Token abcdefghigklmnopqrstuvwxyz123456790'}
apiToken={'Authorization':'Token {}'.format(apiToken)}

dnsServers=dns.resolver.Resolver()
dnsServers.nameservers=dnsList

apiSession=requests.Session()
#if verifySSL:
    #apiSession.verify=False

def checkStatus(address):
    ip=address['address'].split("/")[0]
    if 'Ignore from Automatic Status Update?' in address['custom_fields'] and address['custom_fields']['Ignore from Automatic Status Update?']==True:
        return("{}: ignored".format(ip))
    else:
        data=ping(ip,timeout=10)
        if data is None:
            status=deactiveIPid
        else:
            status=activeIPid

        if address['status']['id']==status:
            return
        else: 
            address['status']=status
            url="{}/ip-addresses/{}/".format(api_base_url,address['id'])
            update={'id':address['id'],'status':status}
            if apiSession.patch(url,headers=apiToken, json=update).status_code==200:
                return("{}: update successful - DATA: {}".format(ip, data))
            else:
                return("{}: update failed".format(ip))

def checkDNS(address):
    ip = (address['address'].split("/"))[0]
    reverseQuery='.'.join(reversed(ip.split("."))) + ".in-addr.arpa"
    try:
        answer=dnsServers.query(reverseQuery, "PTR").response.answer
        for i in answer:
            for j in i.items:
                answer=j.to_text().rstrip('.')
    except:
        return
    if answer==None:
        return
    if address['dns_name']=="" and answer!=None:
        url="{}/ip-addresses/{}/".format(api_base_url,address['id'])
        update={'id':address['id'],'dns_name':answer}
        if apiSession.patch(url,headers=apiToken, json=update).status_code==200:
            return("{}: updated successful".format(ip))
        else:
            return("{}: update failed".format(ip))
    elif address['dns_name']!="" and address['dns_name']!=answer and address['custom_fields']['FQDN']!=answer:
        url="{}/ip-addresses/{}/".format(api_base_url,address['id'])
        address['custom_fields']['FQDN']=answer
        update={'id':address['id'],'custom_fields': address['custom_fields']}
        if apiSession.patch(url,headers=apiToken, json=update).status_code==200:
            return("{}: update successful".format(ip))
        else:
            return("{}: update failed".format(ip))
    else:
        return

#get the prefixes
#get registered IPs in each prefix
#ping IPs that aren't registered
#register them if they aren't 
# if they are 'down' for x amount of days delete delete them
# if they have been changed within the last x amount of days and changes weren't by automation, change them to registered  (view change log https://APIURL/api/extras/object-changes/?changed_object_id=INTEGER)


def getIPaddresses():
    return(json.loads(apiSession.get(api_base_url+"/ip-addresses?limit=0", headers=apiToken).text))

def getPrefixes():
    return(json.loads(apiSession.get(api_base_url+"/prefixes?limit=0", headers=apiToken).text))



if __name__=='__main__':
    pool = Pool(processes=45)
    parser=argparse.ArgumentParser()

    parser.add_argument('-i', '--ip', help='Scan IP addresses for status',action='store_true')
    parser.add_argument('-d', '--dns', help='Check DNS entries',action='store_true')
    parser.add_argument('-l', '--log', help='Log response',action='store_true')

    args=parser.parse_args()
    if args.ip:
        # confirms that script is running as root
        if getuid()!=0:
            print("Program need to be run as root.")
            sys.exit()

        print("Starting IP scan")
        result = pool.map(checkStatus, getIPaddresses()['results'])
        updateCount=failedCount=0
        for index in result:
                if index!=None:
                    if 'update successful' in index:
                        updateCount+=1
                    elif 'update failed' in index:
                        failedCount+=1
                    print(index)
        if args.log and (updateCount>0 or failedCount>0):
            syslog.syslog("Netbox IP Check: {} updated, {} failed".format(updateCount, failedCount))
        

    elif args.dns:
        print("Starting DNS scan")
        result = pool.map(checkDNS, getIPaddresses()['results'])
        updateCount=failedCount=0
        for index in result:
                if index!=None:
                    if 'update successful' in index:
                        updateCount+=1
                    elif 'update failed' in index:
                        failedCount+=1
                    print(index)
        if args.log and (updateCount>0 or failedCount>0):
            syslog.syslog("Netbox DNS Check: {} updated, {} failed".format(updateCount, failedCount))

    else:
        parser.print_help()
    