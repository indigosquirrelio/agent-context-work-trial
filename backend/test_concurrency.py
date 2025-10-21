#!/usr/bin/env python3
"""
Test script for concurrency fixes in file operations.
This script simulates multiple agents and users editing the same files simultaneously.
"""

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import List

from agent_backend.atomic_operations import AtomicFileOperations
from agent_backend.file_locks import get_lock_manager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_FILE = "test_concurrent.py"
WORKSPACE_ROOT = Path(__file__).parent.parent
TEST_CONTENT = '''def hello():
    print("Hello, World!")
    return "success"

def add(a, b):
    return a + b

def multiply(x, y):
    return x * y
'''


class MockAgent:
    """Simulates an agent that edits files."""
    
    def __init__(self, name: str, atomic_ops: AtomicFileOperations):
        self.name = name
        self.atomic_ops = atomic_ops
        self.operations = []
    
    async def edit_file(self, file_path: str, edit_instructions: List[str], description: str):
        """Simulate agent editing a file with surgical edits."""
        try:
            async with self.atomic_ops.atomic_read_modify_write(
                file_path=file_path,
                owner=self.name,
                operation_type="edit",
                context=description
            ) as (current_content, current_etag):
                
                # Apply surgical edits
                modified_content = current_content
                for instruction in edit_instructions:
                    if "print(\"Hello, World!\")" in instruction:
                        modified_content = modified_content.replace(
                            'print("Hello, World!")',
                            'print("Hello from ' + self.name + '!")'
                        )
                    elif "def add(a, b):" in instruction:
                        modified_content = modified_content.replace(
                            "def add(a, b):",
                            f"def add(a, b):  # Modified by {self.name}"
                        )
                
                # Write back
                result = await self.atomic_ops.atomic_write(
                    file_path=file_path,
                    content=modified_content,
                    owner=self.name,
                    expected_etag=current_etag,
                    context=description
                )
                
                if result.success:
                    self.operations.append(f"✅ {description} (v{result.version})")
                    logger.info(f"{self.name}: {description} - SUCCESS")
                else:
                    self.operations.append(f"❌ {description} - FAILED: {result.error}")
                    logger.warning(f"{self.name}: {description} - FAILED: {result.error}")
                
        except Exception as e:
            self.operations.append(f"❌ {description} - ERROR: {e}")
            logger.error(f"{self.name}: {description} - ERROR: {e}")
    
    async def read_file(self, file_path: str):
        """Simulate agent reading a file."""
        try:
            content, etag, version = await self.atomic_ops.atomic_read(
                file_path=file_path,
                owner=self.name,
                context="read operation"
            )
            self.operations.append(f"📖 Read file (v{version})")
            logger.info(f"{self.name}: Read file successfully (v{version})")
            return content
        except Exception as e:
            self.operations.append(f"❌ Read failed: {e}")
            logger.error(f"{self.name}: Read failed - {e}")
            return None


class MockUser:
    """Simulates a user editing files through the interface."""
    
    def __init__(self, name: str, atomic_ops: AtomicFileOperations):
        self.name = name
        self.atomic_ops = atomic_ops
        self.operations = []
    
    async def edit_file(self, file_path: str, new_content: str, description: str):
        """Simulate user editing a file."""
        try:
            result = await self.atomic_ops.atomic_write(
                file_path=file_path,
                content=new_content,
                owner=self.name,
                context=description
            )
            
            if result.success:
                self.operations.append(f"✅ {description} (v{result.version})")
                logger.info(f"{self.name}: {description} - SUCCESS")
            else:
                self.operations.append(f"❌ {description} - FAILED: {result.error}")
                logger.warning(f"{self.name}: {description} - FAILED: {result.error}")
                
        except Exception as e:
            self.operations.append(f"❌ {description} - ERROR: {e}")
            logger.error(f"{self.name}: {description} - ERROR: {e}")


async def run_concurrency_test():
    """Run the concurrency test with multiple agents and users."""
    logger.info("🚀 Starting concurrency test...")
    
    # Initialize atomic operations
    atomic_ops = AtomicFileOperations(WORKSPACE_ROOT / "files")
    
    # Create test file
    test_file_path = WORKSPACE_ROOT / "files" / TEST_FILE
    test_file_path.parent.mkdir(exist_ok=True)
    test_file_path.write_text(TEST_CONTENT)
    logger.info(f"📝 Created test file: {TEST_FILE}")
    
    # Create mock agents and users
    agents = [
        MockAgent("Agent-Alice", atomic_ops),
        MockAgent("Agent-Bob", atomic_ops),
        MockAgent("Agent-Charlie", atomic_ops),
    ]
    
    users = [
        MockUser("User-Dave", atomic_ops),
        MockUser("User-Eve", atomic_ops),
    ]
    
    # Define test operations
    operations = []
    
    # Agent operations (surgical edits)
    for agent in agents:
        operations.append((
            agent.edit_file,
            TEST_FILE,
            ["print(\"Hello, World!\")", "def add(a, b):"],
            f"Modify hello function and add comments"
        ))
    
    # User operations (full file edits)
    user_content_1 = '''def hello():
    print("Hello from User-Dave!")
    return "success"

def add(a, b):
    return a + b

def multiply(x, y):
    return x * y

def new_function():
    return "Added by User-Dave"
'''
    
    user_content_2 = '''def hello():
    print("Hello from User-Eve!")
    return "success"

def add(a, b):
    return a + b

def multiply(x, y):
    return x * y

def another_function():
    return "Added by User-Eve"
'''
    
    operations.append((users[0].edit_file, TEST_FILE, user_content_1, "Complete rewrite by User-Dave"))
    operations.append((users[1].edit_file, TEST_FILE, user_content_2, "Complete rewrite by User-Eve"))
    
    # Add some read operations
    for agent in agents[:2]:
        operations.append((agent.read_file, TEST_FILE, None, None))
    
    # Shuffle operations to simulate random timing
    random.shuffle(operations)
    
    # Execute operations concurrently
    logger.info("🔄 Executing operations concurrently...")
    tasks = []
    
    for i, (func, *args) in enumerate(operations):
        if args[1] is None:  # Read operation
            task = asyncio.create_task(func(args[0]))
        else:  # Edit operation
            task = asyncio.create_task(func(args[0], args[1], args[2]))
        
        tasks.append(task)
        
        # Add small random delay between task creation
        await asyncio.sleep(random.uniform(0.01, 0.1))
    
    # Wait for all operations to complete
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Print results
    logger.info("\n📊 Test Results:")
    logger.info("=" * 50)
    
    for agent in agents:
        logger.info(f"\n{agent.name}:")
        for op in agent.operations:
            logger.info(f"  {op}")
    
    for user in users:
        logger.info(f"\n{user.name}:")
        for op in user.operations:
            logger.info(f"  {op}")
    
    # Check final file state
    try:
        final_content, etag, version = await atomic_ops.atomic_read(
            file_path=TEST_FILE,
            owner="test",
            context="final check"
        )
        logger.info(f"\n📄 Final file state (v{version}):")
        logger.info("=" * 50)
        logger.info(final_content)
        
        # Check lock status
        lock_manager = get_lock_manager()
        all_locks = lock_manager.get_all_locks()
        logger.info(f"\n🔒 Active locks: {len(all_locks)}")
        for path, lock in all_locks.items():
            logger.info(f"  {path}: {lock.owner} ({lock.operation_type})")
        
    except Exception as e:
        logger.error(f"Error reading final file state: {e}")
    
    # Cleanup
    try:
        test_file_path.unlink()
        logger.info(f"\n🧹 Cleaned up test file: {TEST_FILE}")
    except Exception as e:
        logger.warning(f"Failed to clean up test file: {e}")


async def test_lock_timeout():
    """Test lock timeout functionality."""
    logger.info("\n🔒 Testing lock timeout...")
    
    atomic_ops = AtomicFileOperations(WORKSPACE_ROOT / "files")
    
    # Create a test file
    test_file = "test_lock_timeout.py"
    test_path = WORKSPACE_ROOT / "files" / test_file
    test_path.parent.mkdir(exist_ok=True)
    test_path.write_text("print('test')")
    
    try:
        # Acquire a lock with short timeout
        lock_manager = get_lock_manager()
        async with lock_manager.acquire_lock(
            file_path=test_file,
            owner="test-agent",
            operation_type="write",
            timeout=2.0
        ):
            logger.info("Lock acquired, waiting for timeout...")
            await asyncio.sleep(3)  # Wait longer than timeout
        
        logger.info("Lock should have expired")
        
        # Try to acquire lock again
        async with lock_manager.acquire_lock(
            file_path=test_file,
            owner="test-agent-2",
            operation_type="write",
            timeout=1.0
        ):
            logger.info("Successfully acquired lock after timeout")
    
    except Exception as e:
        logger.error(f"Lock timeout test failed: {e}")
    
    finally:
        # Cleanup
        try:
            test_path.unlink()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(run_concurrency_test())
    asyncio.run(test_lock_timeout())
