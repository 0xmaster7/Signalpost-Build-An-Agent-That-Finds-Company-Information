import asyncio
import unittest
from unittest.mock import patch
from signalpost.network import NetworkGateway

class RedirectedRobotsTests(unittest.TestCase):
    def test_redirected_exact_robots_is_reused_but_disallow_still_enforced(self):
        async def run():
            calls=[]
            class Transport:
                async def request(self,url,headers,timeout):
                    calls.append(url)
                    if url=="https://www.company.no/robots.txt":
                        return 301,{"Location":"https://company.no/robots.txt"},b"",url
                    if url=="https://company.no/robots.txt":
                        return 200,{},b"User-agent: *\nDisallow: /private\nCrawl-delay: 1\n",url
                    return 200,{},b"ok",url
            g=NetworkGateway(transport=Transport(),retries=0)
            with patch("signalpost.network.validate_public_host",return_value=("8.8.8.8",)):
                self.assertEqual(await g.robots_decision("https://www.company.no/","SignalpostBot",allowed_hosts={"company.no","www.company.no"}),("allowed",1))
                self.assertEqual(await g.robots_decision("https://company.no/private","SignalpostBot",allowed_hosts={"company.no","www.company.no"}),("disallowed",1))
                self.assertEqual(await g.robots_decision("https://company.no/public","SignalpostBot",allowed_hosts={"company.no","www.company.no"}),("allowed",1))
            self.assertEqual(calls,["https://www.company.no/robots.txt","https://company.no/robots.txt"])
            self.assertNotIn("https://other.company.no",g._robots)
        asyncio.run(run())

    def test_redirect_to_non_robots_path_is_not_destination_permission(self):
        async def run():
            calls=[]
            class Transport:
                async def request(self,url,headers,timeout):
                    calls.append(url)
                    if url=="https://www.company.no/robots.txt":return 301,{"Location":"https://company.no/rules"},b"",url
                    if url=="https://company.no/rules":return 200,{},b"User-agent: *\nAllow: /\n",url
                    return 503,{},b"",url
            g=NetworkGateway(transport=Transport(),retries=0)
            with patch("signalpost.network.validate_public_host",return_value=("8.8.8.8",)):
                await g.robots_decision("https://www.company.no/","SignalpostBot",allowed_hosts={"company.no","www.company.no"})
                self.assertNotIn("https://company.no",g._robots)
                self.assertEqual((await g.robots_decision("https://company.no/","SignalpostBot",allowed_hosts={"company.no"}))[0],"unreachable")
            self.assertIn("https://company.no/robots.txt",calls)
        asyncio.run(run())

class IdentityQueueTests(unittest.TestCase):
    def test_repeated_navigation_links_do_not_evict_distinct_proof_page(self):
        from signalpost.websites import research_company
        import json
        async def run():
            calls=[]
            class Gateway:
                def set_rate_limit(self,*args):pass
                async def robots_decision(self,*args,**kwargs):return "allowed",None
                async def fetch(self,url,**kwargs):
                    calls.append(url)
                    if url=="https://company.no/":
                        body='<title>Target AS</title>'+('<a href="/contact">Contact</a>'*8)+'<a href="/about">About</a>'
                    elif url=="https://company.no/about":
                        body='<title>Target AS</title><script type="application/ld+json">'+json.dumps({"@type":"Organization","name":"Target AS","identifier":"123456789","url":"https://company.no/"})+'</script>'
                    else:body='<title>Contact Target AS</title>'
                    return 200,{"Content-Type":"text/html"},body.encode(),url,"ok"
            result=await research_company({"organisation_number":"123456789","name":"Target AS",
                "website_candidates":[{"raw":"https://company.no/","source":"registry_live"}]},Gateway(),enable_keyless=False,phase="verify")
            self.assertIn("https://company.no/about",calls)
            self.assertEqual(calls.count("https://company.no/contact"),1)
            self.assertTrue(result.phase_state["accepted_pages"])
        asyncio.run(run())
