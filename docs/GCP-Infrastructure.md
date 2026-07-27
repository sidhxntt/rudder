# GCP Infrastructure for Phase 2

This document outlines the Google Cloud Platform (GCP) infrastructure set up for Phase 2 of the project, including virtual machines, network configurations, and firewall rules.

## Project Details

*   **Project ID:** `invytt-2483d`
*   **GCP Console Link:** [Project Dashboard](https://console.cloud.google.com/home/dashboard?project=invytt-2483d)

## Network Configuration

*   **VPC Network Name:** `rudder-vpc`
*   **Subnet Name:** `rudder-subnet`
*   **Subnet IP Range:** `10.42.0.0/20`
*   **Region:** `asia-south1`
*   **Zone:** `asia-south1-a`
*   **GCP Console Link (VPC Networks):** [VPC Networks](https://console.cloud.google.com/networking/vpc/list?project=invytt-2483d)

## Virtual Machines (VMs)

The following Compute Engine instances have been created:

### rudder-control

*   **Name:** `rudder-control`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `40GB`
*   **Internal IP:** `10.42.0.2`
*   **External IP:** `34.14.195.107`
*   **Tags:** `rudder-control`, `rudder-admin`
*   **Docker Installed:** Yes

### rudder-node-a

*   **Name:** `rudder-node-a`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `50GB`
*   **Internal IP:** `10.42.0.4`
*   **External IP:** `34.47.217.191`
*   **Tags:** `rudder-node`, `rudder-admin`
*   **Docker Installed:** Yes

### rudder-node-b

*   **Name:** `rudder-node-b`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `50GB`
*   **Internal IP:** `10.42.0.3`
*   **External IP:** `8.231.75.210`
*   **Tags:** `rudder-node`, `rudder-admin`
*   **Docker Installed:** Yes

*   **GCP Console Link (VM Instances):** [VM Instances](https://console.cloud.google.com/compute/instances?project=invytt-2483d)

## Firewall Rules

The following firewall rules have been configured for the `rudder-vpc` network:

*   **rudder-control-to-agent**
    *   **Description:** Allows TCP traffic on port `9000` from instances tagged `rudder-control` to instances tagged `rudder-node`.
*   **rudder-agent-to-control**
    *   **Description:** Allows TCP traffic on port `8000` from instances tagged `rudder-node` to instances tagged `rudder-control`.
*   **allow-ssh**
    *   **Description:** Allows TCP traffic on port `22` (SSH) from all IP addresses (`0.0.0.0/0`) to instances tagged `rudder-admin`.

*   **GCP Console Link (Firewall Rules):** [Firewall Rules](https://console.cloud.google.com/networking/firewalls/list?project=invytt-2483d)

## Next Steps

The next phase involves building the application code for node registration, heartbeat, scheduler, and reconciler, which will utilize this infrastructure.
