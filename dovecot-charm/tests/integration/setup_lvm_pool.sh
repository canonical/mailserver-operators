#!/bin/bash
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Creates a Juju LVM storage pool for integration tests.
# Runs after juju bootstrap and model creation, before integration tests.
# The model is expected to already exist and be named "testing".

set -eux

POOL_IMG=/tmp/juju-lvm-pool.img

# Create a 5G sparse image, loop-attach it, build a volume group on it
truncate -s 5G "$POOL_IMG"
LOOPDEV=$(sudo losetup --find --show "$POOL_IMG")
sudo pvcreate "$LOOPDEV"
sudo vgcreate juju-lvm-pool "$LOOPDEV"

# Register the pool with Juju so storage requests can use pool name "lvm"
juju create-storage-pool lvm lvm volume-group=juju-lvm-pool --model testing

# Verify the pool is visible
juju storage-pools --model testing
