#  Copyright Contributors to the Feilong Project.
#  SPDX-License-Identifier: Apache-2.0

# VMCP command handler for Systems Management Ultra Thin Layer
#
# Copyright 2026 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import subprocess
import re
from smtLayer import msgs

modId = 'VCP'
version = "1.0.0"


class VMCPHandler:

    def __init__(self, rh):
        """
        Initialise the handler with a Request Handle.

        Input:
           rh - smtLayer ReqHandle instance
        """
        self._rh = rh

    def _run(self, vmcp_args):
        """
        Execute one vmcp sub-command.

        Builds the full command as:
            sudo /sbin/vmcp <vmcp_args[0]> <vmcp_args[1]> ...

        Input:
           vmcp_args - list of str tokens that follow '/sbin/vmcp',
                       e.g. ["query", "userid"]

        Output:
           dict with keys:
             response   - decoded stdout string; empty string on failure
             overallRC  - 0 on success, non-zero on failure
        """
        rh = self._rh
        cmd = ["sudo", "/sbin/vmcp"] + vmcp_args
        strCmd = ' '.join(cmd)
        rh.printSysLog("Invoking: " + strCmd)
        try:
            raw = subprocess.check_output(
                cmd, close_fds=True, stderr=subprocess.STDOUT)
            return {"response": bytes.decode(raw), "overallRC": 0}
        except subprocess.CalledProcessError as e:
            msg = msgs.msg['0405'][1] % (modId, strCmd, strCmd, e.output)
            rh.printLn("ES", msg)
            rh.updateResults(msgs.msg['0405'][0])
            return {"response": "", "overallRC": e.returncode}
        except Exception as e:
            rh.printLn("ES", msgs.msg['0421'][1] % (
                modId, strCmd, type(e).__name__, str(e)))
            rh.updateResults(msgs.msg['0421'][0])
            return {"response": "", "overallRC": 1}

    def activate(self, userid):
        """
        Activate (autolog) a specific virtual machine on z/VM.

        Input:
           userid - target virtual machine userid (str)

        Output:
           rc - return code from the VMCP XAUTOLOG command
                0 indicates successful activation; non-zero indicates an error.
        """
        rh = self._rh
        rh.printSysLog("Enter VMCPHandler.activate, userid: " + userid)

        args = ["xautolog", userid]
        rc = self._run(args)["overallRC"]

        rh.printSysLog("Exit VMCPHandler.activate, rc: " + str(rc))
        return rc

    def query_image_performance(self, rh):
        """
        Collect system image performance information using VMCP commands.
        Input:
            rh - request handle containing the request information (RequestHandle object)

        Output:
            overallRC - return code (0 for success, 1 for failure)
            response  - output of system image performance
        """
        try:
            results = []
            rh.printSysLog("Enter VMCPHandler.query_image_performance, userid: " + rh.userid)
            handler = VMCPHandler(rh)

            # QUERY PROCESSOR
            processor_output = handler._run(["query", "processor"])
            processor_out = processor_output["response"]
            rc = processor_output["overallRC"]
            if rc != 0:
                raise Exception("QUERY PROCESSOR failed: %s" % processor_out)

            cpu_count = len(re.findall(r"^PROCESSOR", processor_out, re.MULTILINE))
            results.append("CPU_COUNT=%04X" % cpu_count)

            # INDICATE LOAD
            load_output = handler._run(["indicate", "load"])
            load_out = load_output["response"]
            rc = load_output["overallRC"]
            if rc != 0:
                raise Exception("INDICATE LOAD failed: %s" % load_out)

            m = re.search(r"AVGPROC-(\d+)%", load_out)
            if m:
                results.append("CPU_AVERAGE_USE=%d%%" % int(m.group(1)))
            else:
                results.append("CPU_AVERAGE_USE=0%")

            m = re.search(r"PAGING-(\d+)/SEC", load_out)
            if m:
                results.append("PAGING_RATE=%s" % m.group(1))
            else:
                results.append("PAGING_RATE=0")

            # QUERY FRAMES
            frames_output = handler._run(["query", "frames"])
            frames_out = frames_output["response"]
            rc = load_output["overallRC"]
            if rc != 0:
                raise Exception("QUERY FRAMES failed: %s" % frames_out)

            configured = 0

            m = re.search(r"Configured=(\d+)", frames_out)
            if m:
                configured = int(m.group(1))

            results.append("MEMORY_TOTAL=%d" % configured)

            free_frames = 0

            m = re.search(r"GlobalClearedAvail=(\d+)", frames_out)
            if m:
                free_frames += int(m.group(1))

            m = re.search(r"LocalClearedAvail=(\d+)", frames_out)
            if m:
                free_frames += int(m.group(1))

            m = re.search(r"LocalUnclearedAvail=(\d+)", frames_out)
            if m:
                free_frames += int(m.group(1))

            gua = re.findall(r"GlobalUnclearedAvail=(\d+)", frames_out)
            for value in gua:
                free_frames += int(value)

            memory_in_use = configured - free_frames

            results.append("MEMORY_IN_USE=%d" % memory_in_use)

            # QUERY MONITOR
            monitor_output = handler._run(["query", "monitor"])
            monitor_out = monitor_output["response"]
            rc = load_output["overallRC"]
            if rc != 0:
                raise Exception("QUERY MONITOR failed: %s" % monitor_out)

            event_section = monitor_out.split("MONITOR SAMPLE ACTIVE")[0]
            sample_section = monitor_out.split("MONITOR SAMPLE ACTIVE")[-1]

            m = re.search(r"RATE\s+([0-9.]+\s+SECONDS)", sample_section)
            if m:
                results.append("MONITOR_RATE=%s" % m.group(1))

            m = re.search(r"INTERVAL\s+(\d+\s+MINUTES)", sample_section)
            if m:
                results.append("MONITOR_INTERVAL=%s" % m.group(1))

            m = re.search(r"PARTITION\s+([0-9A-F]+)", event_section)
            if m:
                event_count = int(m.group(1), 16) // 1024
                results.append("MONITOR_EVENT_COUNT=%d" % event_count)

            # mapping all the information
            domain_map = {
                "MONITOR": "DOMAIN_MONITOR",
                "PROCESSOR": "DOMAIN_PROCESSOR",
                "STORAGE": "DOMAIN_STORAGE",
                "SCHEDULER": "DOMAIN_SCHEDULER",
                "SEEKS": "DOMAIN_SEEKS",
                "USER": "DOMAIN_USER",
                "I/O": "DOMAIN_I/O",
                "NETWORK": "DOMAIN_NETWORK",
                "ISFC": "DOMAIN_ISFC",
                "APPLDATA": "DOMAIN_APPLDATA",
                "SSI": "DOMAIN_SSI",
                "COMMAND": "DOMAIN_COMMAND",
            }

            for line in event_section.splitlines():
                line = line.strip()

                for vmcp_name, smcli_name in domain_map.items():
                    if line.startswith(vmcp_name):
                        if "ENABLED" in line:
                            state = "ENABLED"
                        else:
                            state = "DISABLED"

                        results.append("%s=%s" % (smcli_name, state))
                        break
            rh.printSysLog("Exit VMCPHandler.query_image_performance, rc: " + str(rc))

            return {"overallRC": 0, "response": "\n".join(results)}

        except Exception as err:
            return {"overallRC": 1, "response": str(err)}

    def ssi_info(self):
        """
        Query and collect z/VM SSI cluster information using VMCP.

        Input:
           None - uses the request handle associated with the VMCPHandler.

        Output:
           Dictionary containing:
              response - list of formatted SSI information
              rc  - return code from the VMCP QUERY SSI command
        """

        rh = self._rh
        rh.printSysLog("Enter VMCPHandler.ssi_info")

        args = ['QUERY SSI']

        results = self._run(args)

        vmcp_response = results["response"]
        rc = results["overallRC"]

        # Host is not a member of an SSI cluster
        if "This system is not a member of an SSI cluster." in vmcp_response:
            rh.printSysLog(
                "Exit VMCPHandler.ssi_info - Host is not a member of an SSI cluster."
            )
            return {"response": [], "rc": rc}

        response = []

        # Parse SSI information
        ssi_name = re.search(r"SSI Name:\s*(.+)", vmcp_response)
        ssi_mode = re.search(r"SSI Mode:\s*(.+)", vmcp_response)
        cst = re.search(r"Cross-System Timeouts:\s*(.+)", vmcp_response)
        pdr = re.search(
            r"SSI Persistent Data Record \(PDR\) device:\s*(\S+)\s+on\s+(\S+)",
            vmcp_response
        )

        if ssi_name:
            response.append(f"ssi_name = {ssi_name.group(1)}")
        if ssi_mode:
            response.append(f"ssi_mode = {ssi_mode.group(1)}")
        if pdr:
            response.append(f"ssi_pdr = {pdr.group(1)}_on_{pdr.group(2)}")
        if cst:
            response.append(f"cross_system_timeouts = {cst.group(1)}")

        # Parse member information
        member_pattern = re.compile(
            r"^\s*(\d+)\s+(\S+)\s+(\S+)"
            r"(?:\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})"
            r"\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2}))?$",
            re.MULTILINE
        )

        member_matches = list(member_pattern.finditer(vmcp_response))

        response.append(f"output.ssiInfoCount = {len(member_matches)}")
        response.append("")

        for match in member_matches:
            (
                slot,
                system_id,
                state,
                pdr_date,
                pdr_time,
                recv_date,
                recv_time,
            ) = match.groups()

            if system_id == "--------":
                system_id = "N/A"

            pdr_hb = (
                f"{pdr_date}_{pdr_time}"
                if pdr_date and pdr_time else "N/A"
            )

            recv_hb = (
                f"{recv_date}_{recv_time}"
                if recv_date and recv_time else "N/A"
            )

            response.extend([
                f"member_slot = {slot}",
                f"member_system_id = {system_id}",
                f"member_state = {state}",
                f"member_pdr_heartbeat = {pdr_hb}",
                f"member_received_heartbeat = {recv_hb}",
                ""
            ])

        rh.printSysLog("Exit VMCPHandler.ssi_info, rc: " + str(rc))

        return {"response": response, "rc": rc}

    def query_attach(self, rh):
        """
        Attach a virtual device to a z/VM guest using the VMCP ATTACH command.

        Input:
           rh - request handle containing:
                parms['vaddr'] - virtual device address
                parms['raddr'] - real device address
                parms['mode']  - device access mode
                               (0 = read-write, 1 = read-only)
                userid          - target guest userid

        Output:
         overallRC - return code (0 for success, 1 for failure)
         response  - VMCP command output
        """

        rh.printSysLog("Enter VMCPHandler.query_attach, userid: " + rh.userid)

        args = ["ATTACH", rh.parms['vaddr'], "TO", rh.userid,
                "AS", rh.parms['raddr']]
        # Add read-only option if requested.
        # rh.parms['mode'] is 0 (read-write) or 1 (read-only).
        # z/VM CP ATTACH uses the keyword READONLY — not "RO" or "1".
        if str(rh.parms.get('mode', 0)) == '1':
            args.append("READONLY")

        response = self._run(args)
        rc = response["overallRC"]

        rh.printSysLog("Exit VMCPHandler.query_attach, rc: " + str(rc))
        return response

    def query_detach(self, rh):
        """
        Detach a virtual device from a z/VM guest using the VMCP DETACH command.

        Input:
           rh - request handle containing:
                parms['vaddr'] - virtual device address to be detached
                userid          - guest userid used for logging

            Output:
             overallRC - return code (0 for success, 1 for failure)
             response  - VMCP command output
        """

        rh.printSysLog("Enter VMCPHandler.query_detach, userid: " + rh.userid)
        args = ["DETACH", rh.parms['vaddr']]

        response = self._run(args)
        rc = response["overallRC"]

        rh.printSysLog("Exit VMCPHandler.query_detach, rc: " + str(rc))
        return response
