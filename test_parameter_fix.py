#!/usr/bin/env python3
"""
Simple test to verify the parameter name fix.
"""

import inspect
from pathlib import Path
import sys

# Add backend to path
sys.path.append('backend')

def test_parameter_names():
    """Test that atomic operations methods have correct parameter names."""
    try:
        from agent_backend.atomic_operations import AtomicFileOperations
        
        # Check method signatures
        atomic_ops = AtomicFileOperations(Path('files'), 'utf-8')
        
        # Check atomic_read method
        read_sig = inspect.signature(atomic_ops.atomic_read)
        read_params = list(read_sig.parameters.keys())
        print(f"atomic_read parameters: {read_params}")
        assert 'file_path' in read_params, "atomic_read should have 'file_path' parameter"
        
        # Check atomic_write method
        write_sig = inspect.signature(atomic_ops.atomic_write)
        write_params = list(write_sig.parameters.keys())
        print(f"atomic_write parameters: {write_params}")
        assert 'file_path' in write_params, "atomic_write should have 'file_path' parameter"
        
        # Check atomic_read_modify_write method
        rmw_sig = inspect.signature(atomic_ops.atomic_read_modify_write)
        rmw_params = list(rmw_sig.parameters.keys())
        print(f"atomic_read_modify_write parameters: {rmw_params}")
        assert 'file_path' in rmw_params, "atomic_read_modify_write should have 'file_path' parameter"
        
        print("✅ All parameter names are correct!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_parameter_names()
    if success:
        print("\n🎉 Parameter name fix verified!")
    else:
        print("\n💥 Parameter name fix failed!")
        sys.exit(1)
